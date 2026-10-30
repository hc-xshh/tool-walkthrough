# Plugins

Reserved (预留). No plugin is required, and none participates in the current flow.

The walkthrough runs as an agent session with normal tools. A plugin is only worth adding if it removes a repeated manual step; it may only do one of:

- auto-generate `harness.json` and the evidence manifest
- auto-build the PDF after `report.md` changes
- post the report to a chat channel (never the source of truth)

Do not add a plugin that edits findings or severity automatically.
