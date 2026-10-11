TradingLab Portable STEP04 candidate - PRIVATE LOCAL REVIEW ONLY

Start.cmd / Check.cmd / Stop.cmd use only the bundled Python and Node.
The default profile is TEST: no market network, real AI or Telegram delivery.
Owned synthetic account data: TradingLab/sandbox/data. Agent data: TradingLab/sandbox/agent.
Logs and control records stay in TradingLab/sandbox. Keep this directory to retain TEST data.
Launch from any working directory, including paths with Chinese text and spaces.
Repeated start is rejected. Stop is graceful and validates instance ownership.
Do not copy real .env, accounts, databases, leases or RC1 runtime state here.
Do not move a running or initialized TEST package: ownership is path-specific.

Telegram recipient authorization is local and private: copy .env.telegram.example
to .env.telegram in TradingLab only after local operator review; approve exactly
one positive private-chat ID. The requested TELEGRAM_CHAT_ID in local .env must
match it exactly. Environment variables and Web/API cannot change the approval.
Missing or invalid approval prevents sending. TEST ignores both private files.
Templates are empty; never package the filled files. Release still requires review.

The historical USER deployment controller is retained for future reviewed production
migration. TEST is the locked default. Production activation/migration is NOT_TESTED
in STEP04 and is never automatic. Do not edit seals or accept new hashes to enable it.

Build: run Setup-Dev.cmd with the locked local Runtime ZIP, then Build-Portable.cmd.
Build accepts -Output <new path beneath project .dev> and -Artifact <locked ZIP>.
Existing output directories are refused. No global Python, Node, pip or npm is used.
Review source/config changes, update source-lock.json with an auditable new version,
then build. The builder never silently refreshes the lock or patches source files.
Historical RC1 and STEP02/03 fingerprints remain reference evidence.

License notices: runtime/python/LICENSE.txt, runtime/node/LICENSE.txt and all
package licenses listed in runtime/runtime-lock.json are retained. This is a notice
inventory, not a grant to publish proprietary TradingLab code or private data.
runtime/files.json and SHA256SUMS seal initial payload. No outer ZIP is produced;
matching extracted file hashes do not claim archive byte reproducibility.
