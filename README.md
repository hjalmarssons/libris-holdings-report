# Libris library holdings report

[View the public report](https://hjalmarssons.github.io/libris-holdings-report/) · [PNG graph](history.png) · [Zoomable map](https://hjalmarssons.github.io/libris-holdings-report/map.html) · [PNG map](map.png)

Välfärd och livsvillkor: Perspektiv på samtida samhällsbilder · ISBN 9789147158324.

This repository independently reads the public Libris API once per Stockholm day. It contains the public report, selected holdings data, and its small collector. No private repository access or deployment key is used. Earlier count history was seeded from the existing tracker; missing days are left blank.

The workflow tries five times daily and skips collection after a successful observation. GitHub can delay or skip scheduled triggers. The report shows its actual observation date. Run the workflow manually to retry publication.

Counts are unique Libris library sigels for this edition, not copies or loan availability.

The daily combined map shows red outlines for Ojämlikhetens dimensioner (the fixed 2026-10-19 snapshot), blue fills for Välfärd och livsvillkor (the latest daily observation), and both styles for libraries holding both books. Hollow grey circles show other active Libris participants with usable coordinates. Networks use one representative location. Coordinates come from KB’s library directory, with documented fallbacks; country outlines are Natural Earth public-domain data. Holding locations refresh with each daily observation; the participant directory refreshes weekly. Cached coordinates are used during directory outages and labelled in the zoomable map. The map works without external tiles or scripts.

## Earlier book comparison

Ojämlikhetens dimensioner (ISBN 9789147111299; Libris tc5b55h5189jw23): **50 unique library sigels**, observed 2026-10-19. This is a fixed, dated snapshot shown as a separate diamond, not a second daily series. The y-axis ends at 50 unless the daily series grows beyond it.

The comparison map now uses the same fixed, dated library list and saved directory coordinates, included in comparison-libraries.json. The combined map is rebuilt after each daily collection and replaces map.svg, map.png, and map.html at their existing links. Combined map data is in combined-library-map.json. The current-book library list and count graph retain their existing meanings. Libraries without usable coordinates are listed as unmapped in the zoomable map.
