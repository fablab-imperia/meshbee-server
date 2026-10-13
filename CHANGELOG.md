# Changelog

## [2.0.0](https://github.com/fablab-imperia/meshbee-server/compare/1.2.0...2.0.0) (2026-10-13)


### ⚠ BREAKING CHANGES

* **api:** share with unknown emails as pending invitations ([#40](https://github.com/fablab-imperia/meshbee-server/issues/40))
* **api:** hive ownership, apiaries and sharing per apiary (#2, #36) ([#39](https://github.com/fablab-imperia/meshbee-server/issues/39))
* **db:** move the schema and its logic into meshbee_core with SQLModel and Alembic ([#13](https://github.com/fablab-imperia/meshbee-server/issues/13)) (#30)

### Features

* **api:** apiary invitations and share notices by email ([#55](https://github.com/fablab-imperia/meshbee-server/issues/55)) ([8688b1d](https://github.com/fablab-imperia/meshbee-server/commit/8688b1dc6c115377a2d0222483b91d3758d57581))
* **api:** configurable outgoing email over any SMTP server ([#53](https://github.com/fablab-imperia/meshbee-server/issues/53)) ([8688b1d](https://github.com/fablab-imperia/meshbee-server/commit/8688b1dc6c115377a2d0222483b91d3758d57581))
* **api:** correct and delete readings, admin page sharing and manual readings ([#21](https://github.com/fablab-imperia/meshbee-server/issues/21), [#42](https://github.com/fablab-imperia/meshbee-server/issues/42)) ([#44](https://github.com/fablab-imperia/meshbee-server/issues/44)) ([8489b93](https://github.com/fablab-imperia/meshbee-server/commit/8489b93a811c8281735cde73234a48d72f8758ff))
* **api:** hive ownership, apiaries and sharing per apiary ([#2](https://github.com/fablab-imperia/meshbee-server/issues/2), [#36](https://github.com/fablab-imperia/meshbee-server/issues/36)) ([#39](https://github.com/fablab-imperia/meshbee-server/issues/39)) ([31d5858](https://github.com/fablab-imperia/meshbee-server/commit/31d585817005b9763fc1e3bfb996b6061f2625c3))
* **api:** lightweight admin page at /admin over the admin API ([#41](https://github.com/fablab-imperia/meshbee-server/issues/41)) ([#43](https://github.com/fablab-imperia/meshbee-server/issues/43)) ([3957568](https://github.com/fablab-imperia/meshbee-server/commit/39575688f06406b60506526dbcbdc230015a2154))
* **api:** share with unknown emails as pending invitations ([#40](https://github.com/fablab-imperia/meshbee-server/issues/40)) ([8688b1d](https://github.com/fablab-imperia/meshbee-server/commit/8688b1dc6c115377a2d0222483b91d3758d57581))
* **auth:** redeemable, revocable refresh tokens backed by token_sessione ([#16](https://github.com/fablab-imperia/meshbee-server/issues/16)) ([#60](https://github.com/fablab-imperia/meshbee-server/issues/60)) ([cda2af3](https://github.com/fablab-imperia/meshbee-server/commit/cda2af391e91c273b4f0c3c7fe277b07f6a88cd2))
* **auth:** self-service password reset by email ([#54](https://github.com/fablab-imperia/meshbee-server/issues/54)) ([8688b1d](https://github.com/fablab-imperia/meshbee-server/commit/8688b1dc6c115377a2d0222483b91d3758d57581))
* **db:** define the schema in meshbee_core and migrate it with Alembic ([8254be6](https://github.com/fablab-imperia/meshbee-server/commit/8254be6db59dc9f9d33c9275d486ff3e8d6b023e))
* **db:** move the schema and its logic into meshbee_core with SQLModel and Alembic ([#13](https://github.com/fablab-imperia/meshbee-server/issues/13)) ([#30](https://github.com/fablab-imperia/meshbee-server/issues/30)) ([213377f](https://github.com/fablab-imperia/meshbee-server/commit/213377f1c971c1407a257b0eba8cc6fb100f242d))
* **deploy:** production compose layer with Caddy HTTPS ([#52](https://github.com/fablab-imperia/meshbee-server/issues/52)) ([5145346](https://github.com/fablab-imperia/meshbee-server/commit/514534651e0cb604f27e22dc8e2e9002b0c48d23))
* Improve Admin page. Add optional paging on the API list routes ([#50](https://github.com/fablab-imperia/meshbee-server/issues/50)) ([#51](https://github.com/fablab-imperia/meshbee-server/issues/51)) ([8a1b4fc](https://github.com/fablab-imperia/meshbee-server/commit/8a1b4fc604279f1c8e6e7115b1adcb034b697484))


### Bug Fixes

* drop the unused uvicorn __main__ block, run the images as non-root, add SonarQube Cloud rating badges ([#58](https://github.com/fablab-imperia/meshbee-server/issues/58)) ([b6a9e93](https://github.com/fablab-imperia/meshbee-server/commit/b6a9e9333081459d9e8b3381a14bff80564f1f08))
* **mqtt:** store an out-of-range measurement as null instead of dropping the reading ([42eceb7](https://github.com/fablab-imperia/meshbee-server/commit/42eceb7904215f99e58aedd1943513146fa6d4f9))
* **mqtt:** store an out-of-range measurement as null instead of dropping the reading ([#48](https://github.com/fablab-imperia/meshbee-server/issues/48)) ([#49](https://github.com/fablab-imperia/meshbee-server/issues/49)) ([42eceb7](https://github.com/fablab-imperia/meshbee-server/commit/42eceb7904215f99e58aedd1943513146fa6d4f9))
