# Libris library holdings report

[View the public report](https://hjalmarssons.github.io/libris-holdings-report/) · [PNG graph](history.png)

Välfärd och livsvillkor: Perspektiv på samtida samhällsbilder · ISBN 9789147158324.

This repository independently reads the public Libris API once per Stockholm day. It contains the public report, selected holdings data, and its small collector. No private repository access or deployment key is used. Earlier count history was seeded from the existing tracker; missing days are left blank.

The workflow tries five times daily and skips collection after a successful observation. GitHub can delay or skip scheduled triggers. The report shows its actual observation date. Run the workflow manually to retry publication.

Counts are unique Libris library sigels for this edition, not copies or loan availability.
