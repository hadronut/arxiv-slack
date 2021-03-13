# arxiv-slack

[![arXiv](https://github.com/hadronut/arxiv-slack/actions/workflows/arxiv.yml/badge.svg)](https://github.com/hadronut/arxiv-slack/actions/workflows/arxiv.yml)

## How to Use

1. Fork this repository.
2. Add `category` and corresponding `webhook_url_name` to config.yml.
3. Add [incoming webhook URL](https://api.slack.com/messaging/webhooks) to [GitHub repository secret](https://docs.github.com/en/actions/reference/encrypted-secrets) with the name of `webhook_url_name`.
4. Add the secret to .github/workflows/arxiv.yml.
