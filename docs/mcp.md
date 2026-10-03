# Use Haggle from your AI chat

Haggle searches a simulated Swedish marketplace. Sellers and purchases are simulated.
You approve the opening messages, then choose whether to confirm a deal.

## Gemini CLI

Install once in your terminal:

```sh
gemini extensions install https://github.com/Zawaer/haggle
```

For an existing installation, run `gemini extensions update haggle`. Restart Gemini CLI afterward.
The extension includes the skill, MCP connection and `/haggle` command.

```text
/haggle MacBook Air 13-inch M1, 8 GB RAM, 256 GB SSD, battery at least 80%,
maximum 4,500 SEK, pickup in Stockholm.
```

Give a maximum budget in SEK. Haggle asks only for missing essentials, shows a shortlist and drafts,
and waits for your choice. Reply with the displayed letters, for example “A and C”. Later, pick a
specific deal to confirm. You can also say “check progress” or provide an existing dashboard link.

## Claude Code

In Claude Code:

```text
/plugin marketplace add Zawaer/haggle
/plugin install haggle@haggle-marketplace
```

Restart Claude Code, then describe what you want to buy. The plugin includes the same skill and MCP
connection. Use `/mcp` to check that Haggle is connected.

## Other MCP clients

Add a **Streamable HTTP** server with this URL:

```text
https://haggle-p61s.onrender.com/mcp/
```

The public hackathon demo needs no login. Both `/mcp` and `/mcp/` work, including browser preflight.
Each client's configuration format differs; use its HTTP-server setup rather than a stdio command.
If your client supports skills, add [the Haggle skill](../skills/haggle/SKILL.md).

## If something goes wrong

- **Not connected:** check the URL, reconnect and retry once. The free Render service can take about
  a minute to wake up after being idle. Gemini's extension allows extra connection time for this.
- **Still working:** follow the dashboard link. Model work continues between tool calls; long polls
  last at most 30 seconds and the skill stops after four polls per turn.
- **Lost response while starting:** clients can retry with the same `request_id` and complete brief
  to retrieve the same hunt. Older clients get a two-minute duplicate-start window per client.
- **Missing hunt:** the free server's local storage can disappear on redeploy or restart. Start a new
  hunt with the complete brief. This demo does not promise durable storage.
- **Paused hunt:** ask to resume it. New drafts still need approval. A lost client connection no longer
  cancels recovery or leaves it stuck in `recovering`.
- **Choice saved, notifications pending:** check progress before reporting that the seller was notified.

Release 1.3.0 exposes eight tools, including `listing_details`, and marks tool failures with MCP's
`isError` flag. The MCP initialize response and `/api/info` report the running version, so a local
extension update can be distinguished from a server deployment.

For optional authenticated deployments, `HAGGLE_MCP_ORIGINS` is a comma-separated allowlist of browser
origins. Bearer authentication is still required there; normal website writes retain their origin check.
