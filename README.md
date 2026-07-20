# MSc-dissertation
This is the private repo for the MSc dissertation "Conflict Detection and Resolution among Temporary Fixes and Permanent Driving Rules in Autonomous Driving Systems"

# Z3-Based Conflict Detection for Autonomous Driving Rules

This project parses autonomous-driving strategy rules written in a small domain-specific language (DSL), converts them into Z3 constraints, and checks whether two rules produce incompatible actions when they are active in the same scenario.

## Features

- Parses rules into `trigger`, `condition`, and `then` sections.
- Collects variables and infers `Int`, `Real`, `Bool`, and `String` types.
- Converts variable into Z3 constraints.
- Checks whether an individual rule is internally consistent.
- Compares every pair of rules.
- Reports `Conflict` or `No conflict`.
- Generates JSON files and a human-readable conflict report.
- Uses Z3 unsatisfiable cores to identify the exact constraints involved in a real conflict.

## Requirements

- Python 3.10 or later
- `z3-solver`

Install the dependency:

```bash
python -m pip install z3-solver
```

The package is installed as `z3-solver`, but imported as:

```python
from z3 import *
```

Do not install the unrelated package named only `z3`.

## Project Structure

```text
dissertation code/
├── Rules encoder/
│   ├── rule_parser_z3.py
│   ├── FIXDRIVE strategy repair.txt
│   ├── formatted_rules.json
│   ├── variables.json
│   ├── variable_types.json
│   ├── z3_rules.json
│   ├── single_rule_results.json
│   ├── conflict_results.json
│   ├── conflicts_only.json
│   └── conflict_report.txt
└── README.md
```

The JSON and report files are created automatically when the parser runs.


## Condition Conversion

Z3 cannot automatically understand the meaning of a DSL name such as:

```text
front_vehicle_closer_than(10)
```

Each condition must therefore be mapped to an ADS variable, type, and operator in `CONDITION_DEFINITIONS`.

```python
CONDITION_DEFINITIONS = {
    "front_vehicle_closer_than": {
        "variable": "front_distance",
        "type": "Int",
        "operator": "<",
    },
    "traffic_light_distance_leq": {
        "variable": "traffic_light_distance",
        "type": "Int",
        "operator": "<=",
    },
    "is_traffic_light": {
        "variable": "traffic_light_color",
        "type": "String",
        "operator": "==",
    },
}
```

Examples:

```text
front_vehicle_closer_than(10)
-> front_distance < 10
```

```text
traffic_light_distance_leq(10)
-> traffic_light_distance <= 10
```

```text
is_traffic_light(red)
-> traffic_light_color == "red"
```

To support a new condition, add another entry:

```python
"vehicle_speed_greater_than": {
    "variable": "vehicle_speed",
    "type": "Int",
    "operator": ">",
}
```

## Action Conversion

An action becomes an equality constraint.

```text
follow_dist(10)
-> follow_dist == 10
```

Every action is treated as a separate variable by default:

```python
ACTION_ALIASES = {}
```

This is important because unrelated parameters must not be merged.

For example:

```text
dynamic_obstacle_stop_dist(10)
traffic_light_stop_dist(5)
```

should normally become:

```text
dynamic_obstacle_stop_dist == 10
traffic_light_stop_dist == 5
```

These constraints are compatible because they refer to different variables.

Only add aliases when ADS source-code analysis confirms that two action names modify the same underlying parameter.

```python
ACTION_ALIASES = {
    "action_name_a": "shared_parameter",
    "action_name_b": "shared_parameter",
}
```

With this mapping:

```text
action_name_a(10)
action_name_b(5)
```

becomes:

```text
shared_parameter == 10
shared_parameter == 5
```

Z3 then reports a conflict because one variable cannot equal two different values at the same time.

## Conflict-Detection Logic

Two checks are performed for each pair of rules.

### 1. Condition compatibility

The first solver checks:

```text
rule1 conditions AND rule2 conditions
```

- `sat`: both rules can be activated together.
- `unsat`: the rules cannot occur in the same scenario.

If the conditions are `unsat`, the pair is not classified as an action conflict.

### 2. Combined action compatibility

When the conditions are satisfiable, the second solver checks:

```text
rule1 conditions
AND rule2 conditions
AND rule1 actions
AND rule2 actions
```

- `sat`: no conflict.
- `unsat`: conflict.

A conflict is therefore reported only when both rules can be activated together but their actions cannot hold together.

## Running the Program

Run the script from the project root:

```bash
python -u "Rules encoder/rule_parser_z3.py"
```

The input file is configured near the top of the program:

```python
INPUT_FILE = Path(
    "Rules encoder/FIXDRIVE strategy repair.txt"
)
```

Change this path when using another rule file.

## Generated Output

### `formatted_rules.json`

Stores the parsed rule structure.

### `variables.json`

Stores all variables used in the Z3 model.

### `variable_types.json`

Stores the inferred type of each variable.

```json
{
    "follow_dist": "Int",
    "front_distance": "Int",
    "traffic_light_color": "String"
}
```

### `z3_rules.json`

Stores the original DSL expressions and their Z3 representations.

### `single_rule_results.json`

Reports whether each rule is internally satisfiable.

### `conflict_results.json`

Contains every checked rule pair, including both conflicting and non-conflicting results.


### `conflict_report.txt`

Provides a readable summary.

Example non-conflicting result:

```text
NO CONFLICT: S1 rule1 vs S1 rule2
Reason: The conditions and actions can all be satisfied at the same time.
Condition result: sat
Combined result: sat
```

Example conflict:

```text
CONFLICT: Rule A vs Rule B
Reason: The rules can be activated together, but some resulting constraints cannot hold together.

Exact conflicting constraints:
- Rule: Rule A
  Section: then
  Original: shared_distance(10)
  Z3: shared_distance == 10

- Rule: Rule B
  Section: then
  Original: shared_distance(5)
  Z3: shared_distance == 5
```

## Troubleshooting

### `ImportError: cannot import name 'Bool' from 'z3'`

Remove the incorrect package and reinstall the correct one:

```bash
python -m pip uninstall -y z3 z3-solver
python -m pip install --no-cache-dir z3-solver
```

Test the installation:

```bash
python -c "from z3 import Bool, Int; print(Bool('test'), Int('number'))"
```

### A pair is incorrectly reported as conflicting

Check `ACTION_ALIASES`.

Recommended default:

```python
ACTION_ALIASES = {}
```
