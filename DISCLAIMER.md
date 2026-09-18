# Disclaimer

jevmod is free software under the MIT License (see `LICENSE`). It is provided **as is**, without warranty of any
kind, express or implied, including fitness for a particular purpose.

- **Probabilistic decisions.** jevmod returns probabilities from a machine-learning model and applies thresholds
  you configure. It will produce false positives and false negatives. You, the operator, decide what happens to a
  message; jevmod's defaults only flag.
- **Operator responsibility.** You are responsible for the actions you enable (deleting, muting, banning), for the
  rules you write, for informing your members that automated moderation is in use, and for complying with the
  laws and regulations that apply to your community, including data-protection and content-moderation rules
  such as the GDPR and the EU Digital Services Act.
- **Third-party services.** Message text is sent to TypeSafe's API for judgment under TypeSafe's terms. The
  Discord, Telegram and Reddit adapters are subject to those platforms' developer terms; the Reddit adapter is
  intended for non-commercial use with your own credentials.
- **No affiliation.** jevmod is an independent project by Omar Hernandez. It is not affiliated with, endorsed by
  or supported by TypeSafe, Discord, Telegram, Reddit, Meta, Google or Anthropic. Product names belong to their
  owners.
- **Self-harm signals.** The `selfharm` category exists to alert moderators so a person can reach out. It is not a
  medical or crisis service and must not be used as one.
- **Benchmarks.** Numbers in `BENCHMARK.md` were measured once on public datasets with the defaults at that date;
  results on your traffic will differ.

If you need a warranty, an SLA or legal assurance, jevmod is not the right tool as shipped.
