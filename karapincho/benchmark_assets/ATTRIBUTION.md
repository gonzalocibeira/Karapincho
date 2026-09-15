# Acceptance recordings

These exact MP4 samples are bundled for reproducible performance comparisons. They are derived from the following recordings by transcoding audio to AAC and adding a solid-color video background. They are not used to supply lyrics to the app. The baseline identifies each MP4 with a SHA-256 digest. The two CC BY-SA sample derivatives are distributed under CC BY-SA 3.0; the software has separate licensing.

| Input | Recording | Attribution / license |
|---|---|---|
| Spanish | [La Cucaracha](https://commons.wikimedia.org/wiki/File:La_Cucaracha.ogg), 43 seconds | Elisa (vocals), Sean Buss (guitar), Kenmayer (mix). [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). |
| Japanese | [Sakura Sakura](https://commons.wikimedia.org/wiki/File:Sakura_Sakura.song.ogg), 29 seconds | Kanohara (performance programming); anonymous synthesized vocalist. [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). This is synthesized singing, not a human singer. |
| English/Scots | [Auld Lang Syne](https://commons.wikimedia.org/wiki/File:Auld_Lang_Syne.ogg), 1910 | Frank C. Stanley. Public-domain recording as identified by Wikimedia Commons. Historical recording; not representative of modern clean pop vocals. |

Changes for testing: audio transcoded to AAC inside an MP4 with a solid-color video; the application then generates a karaoke chart. Any distributed derivatives of the CC BY-SA recordings must retain the above attribution and license. Generated benchmark outputs remain local and ignored by git; the three reference MP4s and this attribution are bundled with the application.

These samples establish execution coverage only. Broad lyric accuracy, unusual Japanese readings, duets, and rapid modern vocals require a larger annotated corpus.
