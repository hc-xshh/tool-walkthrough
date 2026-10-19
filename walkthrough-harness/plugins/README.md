# Plugins

None for now.

The walkthrough runs as an agent session with normal tools. If we later add a plugin, it should only do one of:

- auto-generate `meta.json` and the evidence manifest
- auto-build the PDF after `report.md` changes
- post the report to a chat channel (never the source of truth)

Do not add a plugin that edits findings or severity automatically.
