# License and notice

For everyone who runs an OpenDMTQ server, plays on one, or works on the code. It is not legal advice. The site's
footers say what the project is and that the project acts on rights holders' requests.

## The project

OpenDMTQ is an unofficial, non-commercial community project. It is not affiliated with or endorsed by
NEOWIZ. DJMAX and TECHNIKA Q are trademarks of NEOWIZ, and the game is NEOWIZ's copyrighted work.

OpenDMTQ is a server framework. The repository contains no game data: no game client, songs, charts, images or
videos. A server runs only with files its owner provides: their own copy of the game's Android app (APK) and its client
data, which the game cannot start without. Songs are imported separately; a server without them starts the game with
an empty song list. What the repository does hold is OpenDMTQ's own code and what it takes to work with those files:
the names of the game's requests and files and the shapes of the replies the client reads, the short byte patterns and
addresses that `tools/opendmtq_tools/patch_apk.py` looks for in the client.

## For rights holders

This project respects the rights of NEOWIZ and other rights holders. If the copyright holder requests it, this project
may be made private or shut down, in whole or in the part concerned. No lawsuit or formal notice is
needed: a request in the repository's issues is enough, saying who is asking and what it concerns. The
maintainer can act on this repository's own contents; about a fork, another copy or a particular server, please
contact whoever runs it.

## License

OpenDMTQ's own code and documentation are under the MIT License: see [LICENSE](../LICENSE).

The license does not cover the game or its files (client, songs, charts, images, videos). Those are not in
the repository and are not licensed by it.

Nor does it cover third-party parts, which keep their own licenses. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
lists each by where it goes (the site, the phones' runtime and every app built with it, the player for Windows, the PC
client, the tools, the container images and the Windows bundle), and where its full text travels with it.

## If you run a server

- OpenDMTQ works with game files you provide; it does not come with any. Please use files you have the right to
  use, within the rules that apply where you are. They stay on your server: the import keeps them in its `data/`
  folder.
- Players get the app and the songs from your server, with the accounts you make on the admin pages. Broadcasts and
  recordings stay off until you switch them on, and you can remove them at any time.
- If a rights holder asks you to take something down, please do so.

## If you play

- For questions about a server, please ask the person who runs it. How to play on one:
  [playing on a server](play.md).

## Developers and contributors

- The software is provided "as is", without warranty of any kind, as the license states. To the fullest
  extent the law allows, the authors and contributors are not liable for any claim, damages or other
  liability arising from it or from how anyone uses it.
- Authors and contributors do not supply game files, do not tell anyone where to get them, and do not grant
  any right to use them.
- Each server is run independently by its own owner. This project is not a service and does not run servers
  on anyone's behalf.
- Please use, run and change this software in line with copyright law, the game's terms and the laws where you
  live, and only with game files you have the right to use.
- Contributions come in under the same license.
