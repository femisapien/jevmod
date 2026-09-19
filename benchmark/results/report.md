llamaguard done
| set | category | system | n | AUROC | F1@default | P | R | best F1 (th) |
|---|---|---|---|---|---|---|---|---|
| openai_moderation | harassment | jevmod | 1680 | 0.930 | 0.748 | 0.72 | 0.78 | 0.751 (0.80) |
| openai_moderation | harassment | llamaguard | 1680 | 0.805 | 0.681 | 0.73 | 0.63 | 0.681 (0.05) |
| openai_moderation | harassment | shieldgemma | 1680 | 0.914 | 0.618 | 0.51 | 0.80 | 0.663 (0.80) |
| openai_moderation | harassment | toxicbert | 1680 | 0.807 | 0.423 | 0.35 | 0.53 | 0.445 (0.05) |
| openai_moderation | minors | jevmod | 1680 | 0.977 | 0.519 | 0.70 | 0.41 | 0.645 (0.40) |
| openai_moderation | minors | llamaguard | 1680 | 0.590 | 0.248 | 0.33 | 0.20 | 0.248 (0.05) |
| openai_moderation | nsfw | jevmod | 1680 | 0.982 | 0.871 | 0.85 | 0.89 | 0.872 (0.85) |
| openai_moderation | nsfw | llamaguard | 1680 | 0.843 | 0.780 | 0.89 | 0.69 | 0.782 (0.55) |
| openai_moderation | nsfw | shieldgemma | 1680 | 0.968 | 0.800 | 0.72 | 0.89 | 0.851 (0.90) |
| openai_moderation | nsfw | toxicbert | 1680 | 0.876 | 0.549 | 0.54 | 0.56 | 0.574 (0.05) |
| openai_moderation | selfharm | jevmod | 1680 | 0.992 | 0.714 | 0.91 | 0.59 | 0.792 (0.35) |
| openai_moderation | selfharm | llamaguard | 1680 | 0.891 | 0.825 | 0.87 | 0.78 | 0.825 (0.05) |
| openai_moderation | any | jevmod | 1680 | 0.939 | 0.762 | 0.65 | 0.92 | 0.825 (0.80) |
| openai_moderation | any | llamaguard | 1680 | 0.921 | 0.787 | 0.76 | 0.81 | 0.793 (0.80) |
| openai_moderation | any | shieldgemma | 1680 | 0.939 | 0.760 | 0.64 | 0.93 | 0.791 (0.75) |
| openai_moderation | any | toxicbert | 1680 | 0.884 | 0.646 | 0.76 | 0.56 | 0.709 (0.05) |
| civil_comments | harassment | jevmod | 351 | 0.875 | 0.659 | 0.73 | 0.60 | 0.707 (0.50) |
| civil_comments | harassment | llamaguard | 351 | 0.539 | 0.159 | 0.75 | 0.09 | 0.159 (0.05) |
| civil_comments | harassment | shieldgemma | 351 | 0.874 | 0.601 | 0.72 | 0.51 | 0.710 (0.15) |
| civil_comments | harassment | toxicbert | 351 | 0.973 | 0.846 | 0.95 | 0.76 | 0.899 (0.10) |
| civil_comments | any | jevmod | 351 | 0.876 | 0.713 | 0.67 | 0.76 | 0.713 (0.50) |
| civil_comments | any | llamaguard | 351 | 0.592 | 0.169 | 0.59 | 0.10 | 0.293 (0.05) |
| civil_comments | any | shieldgemma | 351 | 0.857 | 0.612 | 0.68 | 0.55 | 0.682 (0.15) |
| civil_comments | any | toxicbert | 351 | 0.973 | 0.846 | 0.95 | 0.76 | 0.899 (0.10) |
| youtube_spam | spam | jevmod | 500 | 0.994 | 0.534 | 1.00 | 0.36 | 0.962 (0.15) |
| youtube_spam | spam | llamaguard | 500 | 0.500 | 0.000 | 0.00 | 0.00 | 0.000 (0.50) |
| youtube_spam | any | jevmod | 500 | 0.960 | 0.904 | 0.92 | 0.89 | 0.921 (0.35) |
| youtube_spam | any | llamaguard | 500 | 0.755 | 0.372 | 0.82 | 0.24 | 0.691 (0.05) |
| youtube_spam | any | shieldgemma | 500 | 0.589 | 0.073 | 0.42 | 0.04 | 0.185 (0.05) |
| youtube_spam | any | toxicbert | 500 | 0.418 | 0.063 | 0.26 | 0.04 | 0.140 (0.05) |

| system | messages | measured | cost / 1,000 msgs | latency / msg |
|---|---|---|---|---|
| jevmod (Jev, 7 categories) | 2504 | 2,515,399 input tokens | $0.0422 | 22 ms (batched 25) |
| Llama Guard 3 8B Q4_K_M (RTX 5080) | 2531 | 49 ms/msg | $0.0041 (GPU time at $0.30/h) | 49 ms |
| ShieldGemma 2B Q8, 4 policies (RTX 5080) | 2531 | 130 ms/msg | $0.0108 (GPU time at $0.30/h) | 130 ms |
| toxic-bert (RTX 5080) | 2531 | 8 ms/msg | $0.0006 (GPU time at $0.30/h) | 8 ms |
| Claude Haiku 4.5 as judge (list price, not run) | | same text + prompt ~1,205 tokens | $1.2255 | ~1,500 ms |

