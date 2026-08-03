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
| `Phase_03_Market_Data.md` | ✅ built (Phase 3) |
| `Phase_04_Indicators.md` | ✅ built (Phase 4) |
| `Phase_05_Strategies.md` | ✅ built (Phase 5) |
| `Phase_06_Risk_Engine.md` | ✅ built (Phase 6) |
| `Phase_07_Execution.md` | ✅ built (Phase 7) |
| `Phase_08_Position_Manager.md` | ✅ built (Phase 8) |
| `Phase_09_Portfolio.md` | 🟡 future (multi-broker) — contract spec written, not built |
| `Phase_10_Database.md` | ✅ built (Phase 10) |
| `Phase_11_Backtesting.md` | ✅ built (Phase 11) |
| `Phase_12_Optimization.md` | ✅ built (Phase 12) |
| `Phase_13_Dashboard.md` | ✅ built (Phase 13) |
| `Phase_14_Monitoring.md` | ✅ built (Phase 14) |
| `Phase_15_Live_Trading.md` | 🟡 token-gated — doc written; live validation blocked on a valid broker token |
| `Phase_16_AI.md` | ✅ built (Phase 16) |
| `Phase_17_Deployment.md` | ✅ built (Phase 17) — ops spec, see also `DEPLOYMENT.md` |

Phase numbering in the original blueprint and the checklist differs slightly;
the checklist table is authoritative for status.
