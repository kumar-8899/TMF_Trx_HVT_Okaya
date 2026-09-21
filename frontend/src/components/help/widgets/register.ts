/** Registers every built-in help widget. Imported for its side effects by the screens that render
 * help markdown (Help.tsx, HelpPanel.tsx) — NOT by Markdown.tsx, because several widgets render
 * markdown themselves and that would be an import cycle. Adding a widget = one line here (the
 * catalog test then accepts `tmf:<name>` blocks that use it). */
import { ChecklistWidget } from "./Checklist";
import { DiagramWidget } from "./Diagrams";
import { ChangelogWidget, FactsWidget, LiveAppWidget, PermissionsMatrixWidget, StepTypesWidget } from "./FactsWidgets";
import { registerWidget } from "./index";
import { OwnershipWidget } from "./Ownership";
import { SkillPickerWidget } from "./SkillPicker";

registerWidget("facts", FactsWidget);
registerWidget("permissions-matrix", PermissionsMatrixWidget);
registerWidget("step-types", StepTypesWidget);
registerWidget("changelog", ChangelogWidget);
registerWidget("live-app", LiveAppWidget);
registerWidget("ownership", OwnershipWidget);
registerWidget("skill-picker", SkillPickerWidget);
registerWidget("checklist", ChecklistWidget);
registerWidget("diagram", DiagramWidget);
