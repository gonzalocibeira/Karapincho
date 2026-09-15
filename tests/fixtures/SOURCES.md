# Acceptance recordings

Run `.venv/bin/python scripts/prepare_fixtures.py` to download these recordings into the ignored `.cache/fixtures` directory and add a plain video background. They are not bundled or used to supply lyrics to the app.

| Input | Recording | Attribution / license |
|---|---|---|
| Spanish | [La Cucaracha](https://commons.wikimedia.org/wiki/File:La_Cucaracha.ogg), 43 seconds | Elisa (vocals), Sean Buss (guitar), Kenmayer (mix). [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). |
| Japanese | [Sakura Sakura](https://commons.wikimedia.org/wiki/File:Sakura_Sakura.song.ogg), 29 seconds | Kanohara (performance programming); anonymous synthesized vocalist. [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). This is synthesized singing, not a human singer. |
| English/Scots | [Auld Lang Syne](https://commons.wikimedia.org/wiki/File:Auld_Lang_Syne.ogg), 1910 | Frank C. Stanley. Public-domain recording as identified by Wikimedia Commons. Historical recording; not representative of modern clean pop vocals. |

Changes for testing: audio transcoded to AAC inside an MP4 with a solid-color video; the application then generates a karaoke chart. Any distributed derivatives of the CC BY-SA recordings must retain the above attribution and license. Test media and generated fixture outputs remain local and ignored by git.

These samples establish execution coverage only. Broad lyric accuracy, unusual Japanese readings, duets, and rapid modern vocals require a larger annotated corpus.
