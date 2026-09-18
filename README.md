# chatgpt-operation

Central repository for reusable ChatGPT operating skills, policies, and reviewable automation contracts.

Initial purpose:

- host portable deterministic skills shared by multiple repositories;
- keep repository-specific policy separate from reusable execution logic;
- distribute skills through versioned Python packages and reusable GitHub workflows;
- pin consumers to exact immutable revisions;
- use pull requests as the review surface for architecture and skill evolution.

The first proposed reusable capability is the repository-mutation skill currently proven in `moose-test-repo`.
