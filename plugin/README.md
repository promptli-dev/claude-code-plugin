# Promptli Comms for Claude

Give Claude its own email address and phone number. With this plugin Claude can send and read email,
send texts, place and schedule phone calls, read call transcripts, and remember notes about contacts,
all as its own Promptli Comms identity.

## What's in the plugin

- **MCP server** `promptli`: the hosted Promptli Comms server at `https://api.comms.promptli.com/mcp`.
  You sign in with your Promptli account over OAuth the first time Claude uses it. No API key is stored.
- **Skill** `promptli-comms`: how to use the tools well (reply in the same thread, keep texts short,
  check contact notes first, never send secrets).
- **Commands** `/promptli-comms:setup`, `/promptli-comms:status` and `/promptli-comms:doctor`.

## Tools

Read-only: `whoami`, `list_conversations`, `get_conversation`, `list_emails`, `list_scheduled`,
`get_call`, `get_call_transcript`, `lookup_contact`, `get_usage`.

Reach real people or cancel something, so they are marked for the client to ask first: `send_email`,
`reply_email`, `send_text`, `place_call`, `schedule_call`, `schedule_text`, `cancel_scheduled`.

Writes only to Promptli: `add_contact_memory`.

New accounts are **live**: approved sends reach real people. For a dry run, use a test-mode key
(`psk_test_`), where emails, texts and calls are simulated and nothing reaches real people.

## Data and network

The plugin talks only to `api.comms.promptli.com`. Messages, call recordings and transcripts, and
contact notes are stored by Promptli Comms. See the [privacy policy](https://promptli.com/privacy)
and [terms](https://promptli.com/terms).

## Optional: answer inbound messages

To have Claude answer people who email, text or call its number, install the optional background
service from the [repository README](https://github.com/promptli-dev/claude-code-plugin#readme).
The plugin works without it.

## Support

Docs: https://promptli.com/docs/comms · Email: info@promptli.com

License: MIT
