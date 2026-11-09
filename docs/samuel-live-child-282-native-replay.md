# Sandbox #282 native Sub-issue replay qualification

Source run: https://github.com/HyungseonSong-plasma/chatgpt-operation/actions/runs/42652102876

The previous branch-triggered run returned SUCCESS at exact SHA `9e699ffa9e86f6beca578456535750f76b71aeaf`.
The live GitHub REST server reports exactly two native Child links (#283, #284) under Parent #282, and each Child's reverse parent REST readback matches internal Parent ID `6289580624`.

This doc-only branch commit intentionally triggers the same isolated workflow for a second, read-only idempotency replay. It MUST skip all Sub-issue POSTs when both links exist. No `samuel` Issue label, state writer, production dispatch, or Controller wake is authorized by this experiment.
