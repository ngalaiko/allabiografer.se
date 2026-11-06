local M = {}

-- An explicit Markdown request opts in; wildcards alone keep browser HTML.
function M.accept(accept)
    local entries = {}
    local explicit_markdown = false
    for entry in (accept or ""):lower():gmatch("[^,]+") do
        local media = entry:match("^%s*([^;%s]+)")
        local quality = 1
        for parameter in entry:gmatch(";([^;]+)") do
            local value = parameter:match("^%s*q%s*=%s*(.-)%s*$")
            if value then
                quality = tonumber(value) or 0
                if quality < 0 or quality > 1 then quality = 0 end
            end
        end
        entries[#entries + 1] = { media = media, quality = quality }
        if media == "text/markdown" and quality > 0 then explicit_markdown = true end
    end
    if not explicit_markdown then return "0" end

    local function quality_for(media)
        local specificity, quality = -1, 0
        for _, entry in ipairs(entries) do
            local rank = entry.media == media and 2 or entry.media == "text/*" and 1
                or entry.media == "*/*" and 0 or -1
            if rank > specificity or (rank == specificity and entry.quality > quality) then
                specificity, quality = rank, entry.quality
            end
        end
        return quality
    end

    return quality_for("text/markdown") >= quality_for("text/html") and "1" or "0"
end

function M.link()
    if ngx.status ~= 200 then return end
    local media = (ngx.header.content_type or ""):match("^[^;]+")
    local city = ngx.var.uri:match("^(/stad/[^/]+/)index%.[^/]+$")
    local path, alternate
    if media == "text/html" and ngx.var.uri:match("%.html$") then
        path = ngx.var.uri:gsub("%.html$", ".md")
        alternate = "text/markdown"
    elseif media == "text/markdown" and ngx.var.uri:match("%.md$") then
        path = ngx.var.uri:gsub("%.md$", ".html")
        alternate = "text/html"
    elseif media == "application/json" and city and ngx.var.uri:match("%.json$") then
        path = city .. "index.html"
        alternate = "text/html"
    else
        return
    end
    -- Encode non-ASCII city names and URI delimiters, but retain path separators.
    path = path:gsub("[^/]+", function(segment) return ngx.escape_uri(segment) end)
    ngx.header["Link"] = '<' .. path .. '>; rel="alternate"; type="' .. alternate .. '"'
    if city and (media == "text/html" or media == "text/markdown") then
        local feed = (city .. "index.json"):gsub("[^/]+", function(segment) return ngx.escape_uri(segment) end)
        ngx.header["Link"] = ngx.header["Link"] .. ', <' .. feed .. '>; rel="alternate"; type="application/json"'
    end
end

return M
