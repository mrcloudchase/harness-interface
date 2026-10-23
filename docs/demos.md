# Demos

Six harnesses taking the same turn, recorded as they ran on a one-box platform against DeepSeek
and OpenAI. Each recording is `scripts/demo.py`: a streamed request that asks the agent to run a
slow shell loop, the package's live stdout relayed as text, a steer sent while the loop runs,
the response the package returned, and the session's trace.

The steer reaches the package as a signal while the CLI is busy. The catalog's packages let the
running call finish and then answer the steer in the same conversation, which is why "counted"
arrives before "stopped" in every recording. [Steer and cancel](steer-and-cancel.md) explains
the mechanism and what is planned for it.

Press play. Idle stretches are shortened; the timings shown are real.

## Claude Code

<div class="cast" data-cast="../assets/casts/claude-code.cast"></div>
<p class="caption">Anthropic shape, DeepSeek. <a href="../catalog/claude-code/">The package</a>.</p>

## Hermes Agent

<div class="cast" data-cast="../assets/casts/hermes.cast"></div>
<p class="caption">Anthropic shape, DeepSeek. <a href="../catalog/hermes/">The package</a>.</p>

## Codex

<div class="cast" data-cast="../assets/casts/codex.cast"></div>
<p class="caption">OpenAI Responses shape, OpenAI. <a href="../catalog/codex/">The package</a>.</p>

## OpenCode

<div class="cast" data-cast="../assets/casts/opencode.cast"></div>
<p class="caption">Anthropic shape, DeepSeek. <a href="../catalog/opencode/">The package</a>.</p>

## pi

<div class="cast" data-cast="../assets/casts/pi.cast"></div>
<p class="caption">Anthropic shape, DeepSeek. <a href="../catalog/pi/">The package</a>.</p>

## Cline

<div class="cast" data-cast="../assets/casts/cline.cast"></div>
<p class="caption">OpenAI chat shape, DeepSeek. <a href="../catalog/cline/">The package</a>.</p>

## Record your own

```bash
asciinema rec -c "python scripts/demo.py --url https://hi.example.com --harness my-harness" my-harness.cast
```

The script reads the key from `HI_KEY` and never prints it, so the recording is safe to share.
