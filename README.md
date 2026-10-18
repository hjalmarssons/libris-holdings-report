# Libris library holdings report

[View the public report](https://hjalmarssons.github.io/libris-holdings-report/) · [PNG graph](history.png) · [Zoomable map](https://hjalmarssons.github.io/libris-holdings-report/map.html) · [PNG map](map.png)

Välfärd och livsvillkor: Perspektiv på samtida samhällsbilder · ISBN 9789147158324.

This repository independently reads the public Libris API once per Stockholm day. It contains the public report, selected holdings data, and its small collector. No private repository access or deployment key is used. Earlier count history was seeded from the existing tracker; missing days are left blank.

The workflow tries five times daily and skips collection after a successful observation. GitHub can delay or skip scheduled triggers. The report shows its actual observation date. Run the workflow manually to retry publication.

Counts are unique Libris library sigels for this edition, not copies or loan availability.

The daily map shows identical blue dots for holdings and hollow grey circles for other active Libris participants with usable coordinates. Networks use one representative location. Coordinates come from KB’s library directory, with documented fallbacks; country outlines are Natural Earth public-domain data. Holding locations refresh with each daily observation; the participant directory refreshes weekly. Cached coordinates are used during directory outages and labelled in the zoomable map. The map works without external tiles or scripts.
