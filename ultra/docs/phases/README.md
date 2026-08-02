# Phases

Each phase is one document following the same template, so the manual is easy
to navigate and audit. Phases are written **before** code lands and updated
**with** it.

## Template

```markdown
# Phase N — Name

## Objective
What this phase delivers and why.

## Architecture
How it fits the system (see `01_System_Architecture.md`).

## Responsibilities
Bullet list of what this layer must and must not do.

## Folder Structure
Files/folders touched.

## Class Diagram
Mermaid class diagram.

## Sequence Diagram
Mermaid sequence diagram of the key flow.

## Data Flow
Inputs → outputs → where it persists.

## Configuration
Settings/environment variables this phase introduces.

## Implementation Steps
Ordered, reviewable steps.

## Testing
Unit / integration / live checks required.

## Definition of Done
Exit criteria (function + blueprint + quality).

## Future Improvements
Deferred items.
```

## Phase Index

> Status is tracked authoritatively in `BLUEPRINT_CHECKLIST.md`. A phase is
> `✅ built` only when its phase doc exists here AND the code is shipped; the
> remaining phases are specified in `01_System_Architecture.md` /
> `02_Domain_Model.md` / `03_Project_Structure.md` and are written into a phase
> doc as they are touched.

| Doc | Status (see BLUEPRINT_CHECKLIST.md) |
|-----|-------------------------------------|
| `Phase_01_Foundation.md` | 🟡 planned — spec in `00_Project_Overview.md` |
| `Phase_02_Broker_Framework.md` | ✅ built (Phase 2) — worked example below |
| `Phase_03_Market_Data.md` | 🟡 planned — spec in `01_System_Architecture.md` |
| `Phase_04_Indicators.md` | 🟡 planned |
| `Phase_05_Strategies.md` | 🟡 planned |
| `Phase_06_Risk_Engine.md` | 🟡 planned |
| `Phase_07_Execution.md` | 🟡 planned |
| `Phase_08_Position_Manager.md` | 🟡 planned |
| `Phase_09_Portfolio.md` | 🟡 future (multi-broker) |
| `Phase_10_Database.md` | 🟡 planned |
| `Phase_11_Backtesting.md` | 🟡 planned |
| `Phase_12_Optimization.md` | 🟡 planned |
| `Phase_13_Dashboard.md` | 🟡 planned |
| `Phase_14_Monitoring.md` | 🟡 planned |
| `Phase_15_Live_Trading.md` | 🟡 token-gated |
| `Phase_16_AI.md` | 🟡 planned |
| `Phase_17_Deployment.md` | ✅ built (Phase 17) — ops spec, see also `DEPLOYMENT.md` |

Phase numbering in the original blueprint and the checklist differs slightly;
the checklist table is authoritative for status.
