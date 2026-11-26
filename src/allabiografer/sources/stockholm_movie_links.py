"""Reviewed identity links for listings whose source metadata is incomplete.

Keys are stable film or event URLs, not title patterns. Values are equivalent
film pages, verified against the listed synopsis, credits, or programme.
"""

REVIEWED_MOVIE_LINKS = {
    # The animated Ralph Bakshi film, not Peter Jackson's adaptation or marathon.
    "https://bio.se/movie/40837": "https://www.biorio.se/sv/filmer/sagan-om-ringen-1978",
    # Nolan's July 2026 film; bio.se identifies the date and featured cast in its synopsis.
    "https://bio.se/movie/42131": "https://www.filmstaden.se/film/the-odyssey",
    # Hamaguchi's film about Marie-Lou and Mari, in an elder-care home outside Paris.
    "https://bio.se/movie/42473": "https://www.filmstaden.se/film/ljuva-framtid",
    # Same supplier parent-film ID and trailer; this listing has English subtitles.
    "https://bio.se/movie/50726": "https://bio.se/movie/42474",
    # The same three Alfons stories, with a different reported programme duration.
    "https://bio.se/movie/42726": "https://www.filmstaden.se/film/bus-och-mysterier-med-alfons-aberg",
    # The same Iñárritu/Tom Cruise film, and the same Haymitch prequel respectively.
    "https://bio.se/movie/43209": "https://www.filmstaden.se/film/digger",
    "https://bio.se/movie/44462": "https://www.biorio.se/sv/filmer/the-hunger-games-sunrise-on-the-reaping",
    # Disney's Hexed, with a Swedish release title and dubbed screenings.
    "https://bio.se/movie/44466": "https://www.filmstaden.se/film/hexe-den-magiska-varlden",
    "https://www.capitolbio.se/filmer/hexe-den-magiska-varlden-premiar-27-nov/4647": "https://www.filmstaden.se/film/hexe-den-magiska-varlden",
    # The 133-minute Bio.se listing matches Rio's 134-minute director's cut, not Aspen's 115-minute listing.
    "https://bio.se/movie/49919": "https://www.biorio.se/sv/filmer/donnie-darko",
    # Fågel Blå gives the longer title for the same Ti West adaptation.
    "https://biofagelbla.se/movie/ebenezer-a-christmas-carol": "https://www.bioaspen.se/movies/ebenezer",
    # These listings specify the same five-hour Bergman version; meal service is not a different movie.
    "https://biofagelbla.se/movie/fanny-och-alexander": "https://www.biorio.se/sv/filmer/fanny-och-alexander",
    "https://www.capitolbio.se/filmer/fanny-och-alexander-julbordsspecial/206": "https://www.biorio.se/sv/filmer/fanny-och-alexander",
    # The Swedish and English titles for Brian Henson's 1992 adaptation.
    "https://www.capitolbio.se/filmer/mupparnas-julsaga-eng-tal-sv-text/4150": "https://www.biorio.se/sv/filmer/the-muppet-christmas-carol",
    # The event description supplies the full title, Pavarotti 90 – The Man Who Moved the World.
    "https://tickets.nortic.se/ticket/event/88882": "https://bio.se/movie/49653",
    # Both synopses name Laurie and Julian Sklar in Steven Soderbergh's film.
    "https://tickets.nortic.se/ticket/event/88432": "https://www.bioaspen.se/movies/the-christophers",
    # Göteborg: original programme titles, synopses and director credits were compared.
    "https://www.capitolgbg.se/produktion/de-gaulle-frihetens-rost": "https://www.filmstaden.se/film/de-gaulle-frihetens-rost",
    "https://www.capitolgbg.se/produktion/sheep-in-the-box": "https://www.filmstaden.se/film/sheep-in-the-box",
    "https://www.capitolgbg.se/produktion/a-talent-for-murder": "https://www.filmstaden.se/film/a-talent-for-murder",
    "https://www.bioroy.se/program/dune-part-three": "https://www.filmstaden.se/film/dune-part-three",
    "https://www.bioguiden.se/filmfokus.aspx?movieid=50cd7ffc-0505-4b98-9257-5817c1acd5d2": "https://www.filmstaden.se/film/the-odyssey",
    "https://www.bioguiden.se/filmfokus.aspx?movieid=2d039b1f-d37b-4adf-8dab-85db09682cb0": "https://www.filmstaden.se/film/hexe-den-magiska-varlden",
    "https://www.bioguiden.se/filmfokus.aspx?movieid=2d5f4e71-e193-49c7-899e-e546263d518e": "https://www.bioroy.se/program/hosten-med-goran",
    # Malmö: gala descriptions and later release dates are not separate films.
    "https://biografspegeln.se/program/dubbelfel": "https://bio.se/movie/49809",
    "https://biografspegeln.se/program/dune-part-three": "https://bio.se/movie/42095",
    "https://biografspegeln.se/program/avengers-doomsday": "https://www.filmstaden.se/film/avengers-doomsday",
    "https://www.nfbio.se/avengers-doomsday?city=malmo": "https://www.filmstaden.se/film/avengers-doomsday",
    "https://www.nfbio.se/casablanca?city=malmo": "https://biografspegeln.se/program/casablanca",
    "https://www.nfbio.se/singin-rain?city=malmo": "https://www.filmstaden.se/film/singin-in-the-rain-klassiker",
    "https://www.nfbio.se/singin-rain?city=uppsala": "https://www.filmstaden.se/film/singin-in-the-rain-klassiker",
    # Nationwide replay: the credits, characters and/or original release identify these works.
    "https://biografspegeln.se/program/amelie-fran-montmartre": "https://bio.se/movie/38656",
    "https://tickets.nortic.se/ticket/event/86805": "https://bio.se/movie/42284",
    "https://www.bioroy.se/program/black-christmas": "https://www.biorio.se/sv/filmer/black-christmas",
    "https://biografspegeln.se/program/cine-blade-runner": "https://www.biorio.se/sv/filmer/blade-runner",
    "https://tickets.nortic.se/ticket/event/88350": "https://biofagelbla.se/movie/breakfast-at-tiffanys",
    "https://bio.se/movie/31079": "https://www.filmstaden.se/film/dune-part-two-klassiker",
    "https://biografspegeln.se/program/ensam-hemma": "https://biofagelbla.se/movie/ensam-hemma",
    "https://biografspegeln.se/program/eyes-wide-shut": "https://biofagelbla.se/movie/eyes-wide-shut",
    "https://bio.se/movie/30223": "https://biofagelbla.se/movie/eyes-wide-shut",
    "https://bio.se/movie/44457": "https://www.filmstaden.se/film/godzilla-minus-zero",
    "https://biografspegeln.se/program/gremlins": "https://biofagelbla.se/movie/gremlins",
    "https://tickets.nortic.se/ticket/event/88063": "https://bio.se/movie/47332",
    "https://biografspegeln.se/program/hosten-med-goran": "https://bio.se/movie/47332",
    "https://tickets.nortic.se/ticket/event/88065": "https://bio.se/movie/49463",
    "https://biografspegeln.se/program/meet-me-in-st-louis": "https://biofagelbla.se/movie/meet-me-in-st-louis",
    "https://bio.se/movie/44493": "https://www.filmstaden.se/film/monster-mia",
    "https://bio.se/movie/49865": "https://www.filmstaden.se/film/ramayana-rise-of-a-legend",
    "https://bio.se/movie/45857": "https://www.filmstaden.se/film/smugglaren",
    "https://bio.se/movie/49387": "https://www.capitolbio.se/filmer/the-devils-1971-otextad/4572",
    "https://biografspegeln.se/program/the-holiday": "https://www.biorio.se/sv/filmer/the-holiday",
    "https://bio.se/movie/44498": "https://www.filmstaden.se/film/the-social-reckoning",
    "https://biografspegeln.se/program/tokyo-godfathers": "https://www.bioaspen.se/movies/tokyo-godfathers",
    "https://bio.se/movie/43444": "https://www.filmstaden.se/film/tony",
    "https://biografspegeln.se/program/twin-peaks-fire-walk-with-me": "https://www.biorio.se/sv/filmer/twin-peaks-fire-walk-with-me",
    "https://bio.se/movie/46175": "https://www.filmstaden.se/film/verity",
    "https://bio.se/movie/50819": "https://biografspegeln.se/program/werwulf",
    # Richard Curtis's film: the London ensemble synopsis or the director and cast agree.
    "https://biografspegeln.se/program/love-actually": "https://www.filmstaden.se/film/love-actually",
    "https://biofagelbla.se/movie/love-actually": "https://www.filmstaden.se/film/love-actually",
    "https://svenskabio.se/filmer/love-actually": "https://www.filmstaden.se/film/love-actually",
    # Same director and synopsis, or the same protagonists and story.
    "https://www.kiviksbio.se/program/extra-visning-1-arne-goes-to-space": "https://bio.se/movie/43279",
    "https://www.kiviksbio.se/program/dubbelfel": "https://bio.se/movie/49809",
    "https://www.kiviksbio.se/program/jonssonligan-wall-enberg": "https://bio.se/movie/42459",
    "https://www.kiviksbio.se/program/november-1963": "https://bio.se/movie/49810",
    "https://www.kiviksbio.se/program/wild-horse-nine": "https://bio.se/movie/48730",
    "https://biografspegeln.se/program/jonssonligan-wall-enberg": "https://bio.se/movie/42459",
    "https://boka.roxy.bio/#/movie/7233": "https://bio.se/movie/44452",
    "https://osbyborgen.se/?pg=6&film=311": "https://bio.se/movie/42095",
    "https://osbyborgen.se/?pg=6&film=322": "https://bio.se/movie/44604",
    "https://osbyborgen.se/?pg=6&film=335": "https://bio.se/movie/43310",
    "https://www.bioguiden.se/filmfokus.aspx?movieid=3757d51f-f99e-43dc-8eca-530ccd44cca1": "https://bio.se/movie/42833",
    "https://www.tickster.com/se/sv/events/yat4vmpc08awptt/2026-12-25/bio-hosten-med-goran": "https://bio.se/movie/47332",
    "https://www.tickster.com/se/sv/events/t431llwthde0cxm/2026-11-27/lek-med-alfons-aberg-tal-svenska-text-svensk": (
        "https://bio.se/movie/40485"
    ),
    "https://www.tickster.com/se/sv/events/g29ggg43vf6jeyc/2026-11-27/paper-tiger-tal-engelska-text-svenska": (
        "https://bio.se/movie/45279"
    ),
    "https://biografspegeln.se/program/national-theatre-the-misanthrope": "https://bio.se/movie/42627",
    "https://biografspegeln.se/program/sing-along-the-nightmare-before-christmas": "https://bio.se/movie/36641",
    "https://biofagelbla.se/movie/gremlins": "https://bio.se/movie/27530",
    # The Cinemateket programmes identify the same films in Stockholm and Göteborg.
    "https://www.capitolgbg.se/produktion/cinemateket-a-fishy-story": "https://bio.se/movie/43166",
    "https://www.capitolgbg.se/produktion/cinemateket-boy-meets-girl": "https://bio.se/movie/43164",
    "https://www.capitolgbg.se/produktion/unga-cinemateket-ensam-hemma-2-vilse-i-new-york": "https://bio.se/movie/43150",
    "https://biografspegeln.se/program/ensam-hemma-2-vilse-i-new-york": "https://bio.se/movie/43150",
    # The specific 2026–27 Met: Live in HD broadcasts, verified by transmission date.
    "https://tickets.nortic.se/ticket/event/85777": "https://bio.se/movie/42999",
    "https://tickets.nortic.se/ticket/event/85779": "https://bio.se/movie/43001",
    "https://tickets.nortic.se/ticket/event/85782": "https://bio.se/movie/43002",
    "https://tickets.nortic.se/ticket/event/85592": "https://bio.se/movie/42997",
    # Nortic listings for these installments in the same release window.
    "https://tickets.nortic.se/ticket/event/85729": "https://bio.se/movie/42459",
    "https://tickets.nortic.se/ticket/event/85975": "https://bio.se/movie/44462",
    # Festival/preview listings, plus Cnema's booking-confirmed Eisenberg film.
    "https://bio.se/movie/49620": "https://bio.se/movie/50569",
    "https://www.capitolgbg.se/produktion/minotaur": "https://bio.se/movie/50292",
    "https://bio.se/movie/50824": "https://biografspegeln.se/program/the-debut",
    # Same documentary and silent film respectively, with different advertised programme times.
    "https://bio.se/movie/49827": "https://bio.se/movie/49922",
    "https://www.bioroy.se/program/terje-vigen": "https://bio.se/movie/1300",
    # Only the 188-minute theatrical edition; the Bergmancenter listing is the long version.
    "https://bio.se/movie/1981": "https://biografspegeln.se/program/fanny-och-alexander",
    "https://www.bioguiden.se/filmfokus.aspx?movieid=fe69b267-f040-4c82-a2f0-c90eed5bcf03": (
        "https://biografspegeln.se/program/fanny-och-alexander"
    ),
    # Bergmancenter and Bio Rio explicitly advertise the complete edition.
    "https://www.bioguiden.se/filmfokus.aspx?movieid=9e9d6380-3393-42ad-83a3-dc6e144b4688": (
        "https://www.biorio.se/sv/filmer/fanny-och-alexander"
    ),
    # Festival entries repeat the regular release's plot and runtime.
    "https://bio.se/movie/50904": "https://bio.se/movie/46865",
    "https://bio.se/movie/50901": "https://bio.se/movie/43960",
    "https://bio.se/movie/50903": "https://bio.se/movie/45159",
    # Hallunda and Skärholmen preview the same first four episodes of the SVT series.
    "https://www.hallundafolketshus.se/events/forhandsvisning-av-arets-julkalender-den-ofrivillige-tomten": (
        "https://bio.se/movie/50827"
    ),
    # Translated titles, language labels and other aliases confirmed by the synopsis or programme.
    "https://boka.roxy.bio/#/movie/7237": "https://bio.se/movie/42364",
    "https://fhbracke.se/film/jonssonligan-och-wall-enberg": "https://bio.se/movie/42459",
    "https://fhbracke.se/carmen-favorit-i-repris": "https://bio.se/movie/46409",
    "https://osbyborgen.se/?pg=6&film=329": "https://bio.se/movie/42284",
    "https://riobiotomelilla.se/#/movie/6987": "https://bio.se/movie/42284",
    "https://osbyborgen.se/?pg=6&film=361": "https://bio.se/movie/49458",
    "https://www.kiviksbio.se/program/eftermiddagsfilm-chopin-en-sonat-i-paris": "https://bio.se/movie/45269",
    "https://biografspegeln.se/program/mupparnas-julsaga": "https://www.biorio.se/sv/filmer/the-muppet-christmas-carol",
    "https://biografspegeln.se/program/my-favorite-things": "https://bio.se/movie/42618",
    "https://tickets.nortic.se/ticket/event/89227": "https://bio.se/movie/42618",
    "https://tickets.nortic.se/ticket/event/86258": "https://bio.se/movie/42997",
    "https://www.biorio.se/sv/filmer/nightmare-before-christmas": "https://bio.se/movie/36641",
    "https://www.tickster.com/se/sv/events/592fl9hwgw83l1c/2026-11-29/julkul-med-greta-gris-svenskt-tal": (
        "https://bio.se/movie/49775"
    ),
    # The anniversary marathon is explicitly sold by both chains; other marathons aren't assumed identical.
    "https://svenskabio.se/filmer/sagan-om-ringen-marathon-extended-edition": (
        "https://www.filmstaden.se/film/sagan-om-ringen-maraton"
    ),
}
