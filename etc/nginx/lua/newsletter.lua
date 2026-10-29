-- This is a narrow recipient API, not a general-purpose PostHog proxy.
local json = require "cjson.safe"
local http = require "resty.http"
local hmac = require "resty.openssl.hmac"
local rand = require "resty.openssl.rand"
local digest = require "resty.openssl.digest"
local hex = require("resty.string").to_hex
local lock = require "resty.lock"
local M = {}

local function fail(status) error({status = status}, 0) end

local function signature(secret, id)
    return hex(assert(assert(hmac.new(secret, "sha256")):final("newsletter-preferences:v1:" .. id)))
end

local function token_for(secret, id) return id .. "." .. signature(secret, id) end

local function verified_id(secret, token)
    if type(token) ~= "string" or #token ~= 97 then fail(401) end
    local id, supplied = token:match("^([a-f0-9]+)%.([a-f0-9]+)$")
    if not id or #id ~= 32 or #supplied ~= 64 then fail(401) end
    local expected, difference = signature(secret, id), 0
    for i = 1, #expected do
        difference = bit.bor(difference, bit.bxor(expected:byte(i), supplied:byte(i)))
    end
    if difference ~= 0 then fail(401) end
    return id
end

local function cities(properties)
    local result, seen = {}, {}
    if type(properties.newsletter_cities) ~= "table" then
        if properties.newsletter_city then fail(409) end
        for key in pairs(properties) do
            if key:match("^newsletter_subscribed_city_") then fail(409) end
        end
        return result
    end
    for _, city in ipairs(properties.newsletter_cities) do
        if type(city) ~= "string" then fail(502) end
        if not seen[city] then result[#result + 1], seen[city] = city, true end
    end
    table.sort(result)
    return result
end

local function identity_for(email)
    local identity = email
    if #identity > 189 then identity = hex(assert(assert(digest.new("sha256")):final(email))) end
    return "newsletter:" .. identity
end

local function encode(data)
    -- Alpine's standard cjson has no empty_array sentinel. Only this known array
    -- needs special handling; cjson still escapes every user-controlled value.
    return assert(json.encode(data)):gsub('"newsletter_cities":{}', '"newsletter_cities":[]')
end

local function run()
    if ngx.req.get_method() ~= "POST" then fail(405) end
    if ngx.var.http_origin and ngx.var.http_origin ~= "https://allabiografer.se" then fail(403) end
    if not (ngx.var.content_type or ""):match("^application/json") then fail(415) end
    local secret = os.getenv("NEWSLETTER_SIGNING_SECRET") or ""
    local key = os.getenv("POSTHOG_PERSONAL_API_KEY") or ""
    local project = os.getenv("POSTHOG_PROJECT_ID") or ""
    local public_key = os.getenv("POSTHOG_PROJECT_TOKEN") or ""
    if #secret < 32 or key == "" or not project:match("^%d+$") or public_key == "" then fail(503) end
    local host = os.getenv("POSTHOG_API_HOST") or "https://eu.posthog.com"
    if host ~= "https://eu.posthog.com" and host ~= "https://us.posthog.com"
        and not host:match("^http://127%.0%.0%.1:%d+$") then fail(503) end
    local base = host .. "/api/projects/" .. project .. "/"

    local function request(method, path, body)
        local client = http.new()
        client:set_timeout(5000)
        local response = client:request_uri(base .. path, {
            method = method, body = body and encode(body),
            headers = {Authorization = "Bearer " .. key, ["Content-Type"] = "application/json"},
            ssl_verify = true, keepalive = false,
        })
        if not response or response.status < 200 or response.status >= 300 then fail(502) end
        if response.body == "" then return {} end
        local data = json.decode(response.body)
        if not data then fail(502) end
        return data
    end

    local function person_lookup(filter)
        local list = request("GET", "persons/?limit=2&" .. filter)
        if list.next ~= nil and list.next ~= json.null then fail(502) end
        if #list.results > 1 then fail(409) end
        if #list.results == 0 then return nil end
        local id = list.results[1].uuid or list.results[1].id
        return request("GET", "persons/" .. ngx.escape_uri(tostring(id)) .. "/")
    end

    local function capture(identity, properties, event)
        local client = http.new()
        client:set_timeout(5000)
        local response = client:request_uri(
            (os.getenv("POSTHOG_CAPTURE_HOST") or "https://eu.i.posthog.com") .. "/i/v0/e/", {
                method = "POST", ssl_verify = true, keepalive = false,
                headers = {["Content-Type"] = "application/json"},
                body = encode({api_key = public_key, event = event, distinct_id = identity,
                    properties = {["$process_person_profile"] = true, ["$geoip_disable"] = true,
                        ["$set"] = properties}}),
            })
        local data = response and json.decode(response.body)
        if not response or response.status ~= 200 or not data
            or (data.status ~= 1 and data.status ~= "Ok") then fail(502) end
    end

    local function wait_for(email, desired)
        for _ = 1, 20 do
            local person = person_lookup("email=" .. ngx.escape_uri(email))
            if person and person.properties.newsletter_preferences_token == desired.newsletter_preferences_token
                and json.encode(cities(person.properties)) == json.encode(cities(desired)) then
                ngx.shared.newsletter_pending:delete(identity_for(email))
                return person
            end
            ngx.sleep(0.5)
        end
        fail(503)
    end

    local function edit(email, transform, event)
        local identity = identity_for(email)
        local mutex = assert(lock:new("newsletter_locks", {timeout = 1, exptime = 300}))
        if not mutex:lock(identity) then fail(503) end
        local ok, result = pcall(function()
            local pending = json.decode(ngx.shared.newsletter_pending:get(identity) or "null")
            local person
            if type(pending) == "table" then
                -- Never resend an uncertain write or let another update overtake it.
                person = wait_for(email, pending)
            else
                person = person_lookup("email=" .. ngx.escape_uri(email))
            end
            local desired = transform(person and person.properties or {})
            if not ngx.shared.newsletter_pending:safe_set(identity, encode(desired)) then fail(503) end
            local distinct_id = person and person.distinct_ids and person.distinct_ids[1] or identity
            capture(distinct_id, desired, event)
            return wait_for(email, desired)
        end)
        mutex:unlock()
        if not ok then error(result, 0) end
        return result
    end

    ngx.req.read_body()
    local body = json.decode(ngx.req.get_body_data() or "")
    if type(body) ~= "table" then fail(400) end
    if ngx.var.uri == "/api/newsletter/signup" then
        local email = type(body.email) == "string" and body.email:match("^%s*(.-)%s*$"):lower()
        if not email or #email > 254 or not email:match("^[^%s@,;<>]+@[^%s@,;<>]+%.[^%s@,;<>]+$")
            or type(body.city) ~= "string" then fail(400) end
        local file = io.open(os.getenv("NEWSLETTER_CITIES_FILE") or
            "/var/www/allabiografer.se/i/newsletter-cities.json", "r")
        if not file then fail(503) end
        local allowed = json.decode(file:read("*a"))
        file:close()
        if not allowed or not allowed[body.city] then fail(400) end
        edit(email, function(properties)
            local memberships, seen = cities(properties), false
            for _, city in ipairs(memberships) do if city == body.city then seen = true end end
            if not seen then memberships[#memberships + 1] = body.city end
            table.sort(memberships)
            local id = properties.newsletter_preferences_id or hex(assert(rand.bytes(16)))
            return {email = email, newsletter_confirmed = "yes", newsletter_cities = memberships,
                newsletter_preferences_id = id, newsletter_preferences_token = token_for(secret, id)}
        end, "newsletter_signup")
        -- Never disclose whether a person exists, or return their bearer token.
        return {success = true}
    end

    if ngx.var.uri ~= "/api/newsletter/preferences" then fail(404) end
    local token = (ngx.var.http_authorization or ""):match("^Bearer (.+)$")
    local id = verified_id(secret, token)
    local filter = {{key = "newsletter_preferences_id", type = "person", operator = "exact", value = {id}}}
    local person = person_lookup("properties=" .. ngx.escape_uri(json.encode(filter)))
    if not person or person.properties.newsletter_preferences_token ~= token then fail(401) end
    local email = person.properties.email
    if type(email) ~= "string" or email == "" then fail(401) end
    if body.unsubscribe ~= nil then
        if body.unsubscribe ~= true or (body.city ~= nil and type(body.city) ~= "string") then fail(400) end
        person = edit(email:lower(), function(properties)
            -- Revalidate after obtaining the same lock as signup.
            if properties.newsletter_preferences_token ~= token then fail(401) end
            local remaining = {}
            if body.city then
                local found = false
                for _, city in ipairs(cities(properties)) do
                    if city ~= body.city then remaining[#remaining + 1] = city else found = true end
                end
                if not found then fail(400) end
            end
            return {newsletter_cities = remaining, newsletter_preferences_id = id,
                newsletter_preferences_token = token}
        end, "newsletter_preferences_updated")
    elseif next(body) ~= nil then fail(400) end

    -- Native email-client unsubscribe remains an independent delivery safeguard.
    -- It does not recreate a second subscription list or a receive boolean.
    local optouts = request("GET", "messaging_preferences/opt_outs/?page_size=100&search=" .. ngx.escape_uri(email))
    if optouts.next ~= nil and optouts.next ~= json.null then fail(502) end
    local blocked = false
    for _, entry in ipairs(optouts.results or optouts) do
        if entry.identifier == email then blocked = true end
    end
    return {cities = cities(person.properties), delivery_blocked = blocked}
end

function M.handle()
    ngx.header["Content-Type"] = "application/json; charset=utf-8"
    ngx.header["Cache-Control"] = "no-store"
    ngx.header["Referrer-Policy"] = "no-referrer"
    local ok, result = pcall(run)
    if not ok then
        ngx.status = type(result) == "table" and result.status or 503
        ngx.say(json.encode({error = "Request failed", status = ngx.status}))
        return
    end
    if result.cities then
        ngx.say('{"delivery_blocked":' .. tostring(result.delivery_blocked) .. ',"cities":' ..
            (#result.cities == 0 and "[]" or json.encode(result.cities)) .. '}')
    else ngx.say(json.encode(result)) end
end

return M
