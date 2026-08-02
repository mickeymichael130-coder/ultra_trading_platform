# Diagrams

Version-controlled Mermaid diagrams for the UATP manual.

## Inventory

| Diagram | Lives in | Status |
|---------|----------|--------|
| Layered architecture | `01_System_Architecture.md` | ✅ |
| Runtime flow (sequence) | `01_System_Architecture.md` | ✅ |
| Broker abstraction | `01_System_Architecture.md` | ✅ |
| Event flow | `01_System_Architecture.md` | ✅ |
| Multi-broker + portfolio | `01_System_Architecture.md` | ✅ |
| Broker framework class/sequence | `phases/Phase_02_Broker_Framework.md` | ✅ |
| Database ER | `phases/Phase_10_Database.md` | 🔜 |
| Deployment / monitoring | `phases/Phase_17_Deployment.md` | 🔜 |
| Trade lifecycle state machine | `phases/Phase_08_Position_Manager.md` | 🔜 |

Mermaid renders in GitHub, VS Code (Markdown preview), and most Markdown
viewers. Keep diagrams inline with their documents rather than as separate
images so they stay in sync with the prose.

To export to PNG/SVG for docs: `npx @mermaid-js/mermaid-cli -i file.mmd -o out.png`.
