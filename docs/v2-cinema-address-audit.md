# v2 cinema address audit

All venue IDs in the local v2 parse snapshots are represented, including older Nortic IDs for Spånga Folkan and Biocafé Tellus. The registry also includes the configured Bioguiden and Cinemascenen venues without saved v2 screenings. Addresses for these additions come from the adapter configuration, except Östergarns Bio, which uses the [venue's published address](https://bygdegardarna.se/ostergarn/bio/).

| Venue | Visiting address | Source |
|---|---|---|
| Alsterbro Folkets Hus | Parkvägen 11 | [Folkets Hus & Parker](https://www.folketshusochparker.se/arrangor/alsterbro-byggnadsforening/) |
| Biograf Aniara | Västra Storgatan 15 | [Gnesta kommun](https://www.gnesta.se/kulturfritid/evenemang/evenemang/biografaniara/bioaniara.4.2aeb89fd1a12f79a5b81957c.html) |
| Bio Borgen | Västra Storgatan 35 | [Osby kommun](https://turism.osby.se/se--gora/upplev-osby-kommun.html) |
| Emmaboda Folkets Hus | Nygatan 8 | [Venue](https://emmabodafolketshus.se/kontakt/) |
| Ersboda Folkets Hus | Byttgränd 13 | [Venue](https://ersbodafolketshus.se/) |
| Flora Biografteater | Idegatan 5 | [Folkets Hus & Parker](https://www.folketshusochparker.se/arrangor/biografteatern-flora/) |
| Folkets Hus Säter | Järnvägsgatan 22 | [Folkets Hus & Parker](https://www.folketshusochparker.se/arrangor/saters-folkets-hus/) |
| Folkets Hus Älvsbyn | Medborgargatan 2 | [Forum Älvsbyn](https://www.forumalvsbyn.se/kontakt/) |
| Folketshus, Ulricehamn | Nygatan 24 | [Venue](https://www.folketshusulricehamn.se/kontakt/) |
| Kiruna Aurora | Stadshustorget 10 | [Venue](https://aurorakiruna.se/praktisk-info/oppettider-och-kontakt) |
| Kulturhuset Finspång | Bergslagsvägen 29 | [Finspångs kommun](https://finspang.se/kulturhuset/kulturhuset-finspang/om-oss/oppettider-i-kulturhuset) |
| Metropol Kultur | Norra Fogdelyckegatan 24 | [Venue](https://metropolkultur.se/kontakt/) |
| Sjöängen | Drottning Kristinas väg 2 | [Venue](https://sjoangen.askersund.se/kontakt.html) |
| Skarpnäcks Kulturhus | Skarpnäcks allé 25 | [Venue](https://skarpnackskulturhus.stockholm/om-oss/hitta-hit/) |
| Bagarmossens Folkets Hus | Lillåvägen 44 | [Venue](https://bagisfh.se/hitta-hit/) |
| Storm | Nedre Långgatan 33 | [Venue](https://www.restaurangstorm.se/17/4/kontakt/) |
| Vallentuna Teater | Gymnasievägen 4 | [Event operator](https://jano.nu/vallentuna-teater) |
| Vilhelmina Folkets Hus | Tingsgatan 8 | [Venue](https://vilhelminafolketshus.se/) |

TODO: Reconcile remaining legacy-only venues and aliases in `data/allabiografer.db`. Verify inherited addresses against venue sources, including entries that contain only a street or building name.
