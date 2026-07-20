import json
import re
from pathlib import Path

from z3 import (
    And,
    Bool,
    BoolVal,
    Int,
    IntVal,
    Real,
    RealVal,
    Solver,
    String,
    StringVal,
    sat,
    unsat,
)



INPUT_FILE = Path("Rules encoder/FIXDRIVE strategy repair.txt")
OUTPUT_DIRECTORY = Path("Rules encoder")

# basic configure
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



ACTION_ALIASES = {}


FUNCTION_PATTERN = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)$"
)


# rule parser, to formet the rule

def parse_rules(text):
    """Convert the DSL text into a list of rule dictionaries."""

    rules = []
    current_rule = None
    current_section = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("rule "):
            if current_rule is not None:
                rules.append(current_rule)

            match = re.match(r'rule\s+"(.+)"', line)

            if not match:
                raise ValueError(f"Invalid rule line: {line}")

            current_rule = {
                "name": match.group(1),
                "trigger": [],
                "condition": [],
                "then": [],
            }

            current_section = None

        elif line in {"trigger", "condition", "then"}:
            if current_rule is None:
                raise ValueError(
                    f"Section appears before a rule: {line}"
                )

            current_section = line

        elif line == "end":
            if current_rule is not None:
                rules.append(current_rule)
                current_rule = None
                current_section = None

        else:
            if current_rule is None or current_section is None:
                raise ValueError(f"Unexpected line: {line}")

            current_rule[current_section].append(line)

    if current_rule is not None:
        rules.append(current_rule)

    return rules


# collect the variable and the type of the variable
# link them together to make the further step become easier

def split_function(expression):
    """
    Convert:
        follow_dist(10)

    into:
        ("follow_dist", "10")
    """

    match = FUNCTION_PATTERN.fullmatch(expression.strip())

    if not match:
        raise ValueError(
            f"Invalid function expression: {expression}"
        )

    function_name = match.group(1)
    argument = match.group(2).strip()

    return function_name, argument


def infer_value_type(value):
    """Determine the Z3 type represented by a text value."""

    value = value.strip()

    if value.lower() in {"true", "false"}:
        return "Bool"

    if re.fullmatch(r"[-+]?\d+", value):
        return "Int"

    if re.fullmatch(
        r"[-+]?(?:\d+\.\d*|\.\d+)",
        value,
    ):
        return "Real"

    return "String"


def add_variable_type(variable_types, variable_name, variable_type):
    """Add a variable type and reject inconsistent declarations."""

    existing_type = variable_types.get(variable_name)

    if existing_type is not None and existing_type != variable_type:
        raise TypeError(
            f"Variable '{variable_name}' has conflicting types: "
            f"{existing_type} and {variable_type}"
        )

    variable_types[variable_name] = variable_type


def collect_variables(parsed_rules):
    """
    Collect the actual ADS variables used by Z3.

    Condition function names are converted to their underlying ADS
    variables using CONDITION_DEFINITIONS.

    Action function names are converted using ACTION_ALIASES.
    """

    variable_types = {}

    for rule in parsed_rules:

        for expression in rule["trigger"]:
            if expression.lower() == "always":
                continue

            condition_name, _ = split_function(expression)

            if condition_name not in CONDITION_DEFINITIONS:
                raise ValueError(
                    f"Unknown trigger condition: {condition_name}"
                )

            definition = CONDITION_DEFINITIONS[condition_name]

            add_variable_type(
                variable_types,
                definition["variable"],
                definition["type"],
            )

        for expression in rule["condition"]:
            condition_name, _ = split_function(expression)

            if condition_name not in CONDITION_DEFINITIONS:
                raise ValueError(
                    f"Unknown condition: {condition_name}"
                )

            definition = CONDITION_DEFINITIONS[condition_name]

            add_variable_type(
                variable_types,
                definition["variable"],
                definition["type"],
            )

        for expression in rule["then"]:
            action_name, argument = split_function(expression)

            target_name = ACTION_ALIASES.get(
                action_name,
                action_name,
            )

            action_type = infer_value_type(argument)

            add_variable_type(
                variable_types,
                target_name,
                action_type,
            )

    sorted_types = dict(sorted(variable_types.items()))

    return sorted(sorted_types.keys()), sorted_types


# convert the variable and the type into z3 formet

def create_z3_variable(variable_name, variable_type):
    """Create one symbolic Z3 variable."""

    if variable_type == "Bool":
        return Bool(variable_name)

    if variable_type == "Int":
        return Int(variable_name)

    if variable_type == "Real":
        return Real(variable_name)

    if variable_type == "String":
        return String(variable_name)

    raise ValueError(
        f"Unsupported type for '{variable_name}': {variable_type}"
    )


def create_z3_variables(variable_types):

    return {
        variable_name: create_z3_variable(
            variable_name,
            variable_type,
        )
        for variable_name, variable_type in variable_types.items()
    }


def convert_value_to_z3(value, variable_type):
    """Convert into a Z3 value."""

    value = value.strip()

    if variable_type == "Bool":
        if value.lower() == "true":
            return BoolVal(True)

        if value.lower() == "false":
            return BoolVal(False)

        raise ValueError(f"Invalid Boolean value: {value}")

    if variable_type == "Int":
        return IntVal(value)

    if variable_type == "Real":
        return RealVal(value)

    if variable_type == "String":
        return StringVal(value.strip("\"'"))

    raise ValueError(
        f"Unsupported value type: {variable_type}"
    )


def apply_operator(z3_variable, operator, z3_value):

    if operator == "<":
        return z3_variable < z3_value

    if operator == "<=":
        return z3_variable <= z3_value

    if operator == ">":
        return z3_variable > z3_value

    if operator == ">=":
        return z3_variable >= z3_value

    if operator == "==":
        return z3_variable == z3_value

    if operator == "!=":
        return z3_variable != z3_value

    raise ValueError(f"Unsupported operator: {operator}")


def parse_condition(condition_string, z3_variables):

    condition_name, argument = split_function(condition_string)

    if condition_name not in CONDITION_DEFINITIONS:
        raise ValueError(
            f"Unknown condition: {condition_string}"
        )

    definition = CONDITION_DEFINITIONS[condition_name]

    variable_name = definition["variable"]
    variable_type = definition["type"]
    operator = definition["operator"]

    z3_variable = z3_variables[variable_name]
    z3_value = convert_value_to_z3(
        argument,
        variable_type,
    )

    return apply_operator(
        z3_variable,
        operator,
        z3_value,
    )


def parse_action(
    action_string,
    z3_variables,
    variable_types,
):

    action_name, argument = split_function(action_string)

    target_name = ACTION_ALIASES.get(
        action_name,
        action_name,
    )

    variable_type = variable_types[target_name]

    z3_variable = z3_variables[target_name]
    z3_value = convert_value_to_z3(
        argument,
        variable_type,
    )

    return z3_variable == z3_value


def combine_expressions(expressions):

    if not expressions:
        return BoolVal(True)

    return And(*expressions)


def rule_to_z3_parts(
    rule,
    z3_variables,
    variable_types,
):


    condition_expressions = []

    for trigger in rule["trigger"]:
        if trigger.lower() == "always":
            condition_expressions.append(BoolVal(True))
        else:
            condition_expressions.append(
                parse_condition(
                    trigger,
                    z3_variables,
                )
            )

    for condition in rule["condition"]:
        condition_expressions.append(
            parse_condition(
                condition,
                z3_variables,
            )
        )

    action_expressions = [
        parse_action(
            action,
            z3_variables,
            variable_types,
        )
        for action in rule["then"]
    ]

    return (
        combine_expressions(condition_expressions),
        combine_expressions(action_expressions),
    )


# z3 conflict detect

def check_single_rule(
    rule,
    z3_variables,
    variable_types,
):
    """Check whether one rule is internally satisfiable."""

    condition, action = rule_to_z3_parts(
        rule,
        z3_variables,
        variable_types,
    )

    solver = Solver()
    solver.add(condition, action)

    return solver.check()


def check_conflict(
    rule1,
    rule2,
    z3_variables,
    variable_types,
):


    condition1, action1 = rule_to_z3_parts(
        rule1,
        z3_variables,
        variable_types,
    )

    condition2, action2 = rule_to_z3_parts(
        rule2,
        z3_variables,
        variable_types,
    )

    # First determine whether both rules can trigger together.
    condition_solver = Solver()
    condition_solver.add(condition1, condition2)

    condition_result = condition_solver.check()

    if condition_result == unsat:
        return {
            "conflict": False,
            "reason": "The rule conditions cannot occur together.",
            "condition_result": str(condition_result),
            "combined_result": None,
        }

    # Then determine whether both sets of actions can hold together.
    combined_solver = Solver()
    combined_solver.add(
        condition1,
        condition2,
        action1,
        action2,
    )

    combined_result = combined_solver.check()

    if combined_result == unsat:
        return {
            "conflict": True,
            "reason": (
                "The conditions can occur together, but the actions "
                "cannot be satisfied together."
            ),
            "condition_result": str(condition_result),
            "combined_result": str(combined_result),
        }

    model = combined_solver.model()

    return {
        "conflict": False,
        "reason": (
            "The conditions and actions can be satisfied together."
        ),
        "condition_result": str(condition_result),
        "combined_result": str(combined_result),
        "model": str(model),
    }

# output file and the conflcit report

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as output_file:
        json.dump(
            data,
            output_file,
            ensure_ascii=False,
            indent=4,
        )


def main():
    with INPUT_FILE.open("r", encoding="utf-8") as input_file:
        text = input_file.read()

    parsed_rules = parse_rules(text)

    collected_variables, variable_types = collect_variables(
        parsed_rules
    )

    z3_variables = create_z3_variables(
        variable_types
    )

    print("Parsed rules:")
    for rule in parsed_rules:
        print(rule)

    print("\nCollected variables:")
    for variable_name in collected_variables:
        print(variable_name)

    print("\nVariable types:")
    for variable_name, variable_type in variable_types.items():
        print(f"{variable_name}: {variable_type}")

    print("\nZ3 variables:")
    for variable_name, z3_variable in z3_variables.items():
        print(
            f"{variable_name}: "
            f"{z3_variable} ({z3_variable.sort()})"
        )

    print("\nZ3 rule representation:")

    z3_rule_output = []

    for rule in parsed_rules:
        condition, action = rule_to_z3_parts(
            rule,
            z3_variables,
            variable_types,
        )

        print(f"\nRule: {rule['name']}")
        print(f"Condition: {condition}")
        print(f"Action: {action}")

        z3_rule_output.append(
            {
                "name": rule["name"],
                "condition": str(condition),
                "action": str(action),
            }
        )

    print("\nSingle-rule consistency:")

    for rule in parsed_rules:
        result = check_single_rule(
            rule,
            z3_variables,
            variable_types,
        )

        if result == unsat:
            print(
                f"Internal conflict: {rule['name']} "
                f"(the rule is unsatisfiable by itself)"
            )
        else:
            print(
                f"Consistent rule: {rule['name']}"
            )

    print("\nPairwise conflict detection:")

    conflict_results = []
    conflicts_only = []
    report_lines = [
        "Z3 Conflict Detection Report",
        "=" * 40,
        "",
    ]

    for i in range(len(parsed_rules)):
        for j in range(i + 1, len(parsed_rules)):
            rule1 = parsed_rules[i]
            rule2 = parsed_rules[j]

            result = check_conflict(
                rule1,
                rule2,
                z3_variables,
                variable_types,
            )

            condition1, action1 = rule_to_z3_parts(
                rule1,
                z3_variables,
                variable_types,
            )

            condition2, action2 = rule_to_z3_parts(
                rule2,
                z3_variables,
                variable_types,
            )

            output = {
                "rule1": rule1["name"],
                "rule2": rule2["name"],
                "conflict": result["conflict"],
                "reason": result["reason"],
                "rule1_condition": str(condition1),
                "rule1_action": str(action1),
                "rule2_condition": str(condition2),
                "rule2_action": str(action2),
                "condition_result": result.get("condition_result"),
                "combined_result": result.get("combined_result"),
            }

            if "model" in result:
                output["model"] = result["model"]

            conflict_results.append(output)

            if result["conflict"]:
                conflicts_only.append(output)

                print(
                    f"Conflict: {rule1['name']} vs "
                    f"{rule2['name']}"
                )
                print(f"Reason: {result['reason']}")

                report_lines.extend(
                    [
                        f"CONFLICT: {rule1['name']} vs {rule2['name']}",
                        f"Reason: {result['reason']}",
                        "",
                        f"{rule1['name']} condition:",
                        str(condition1),
                        f"{rule1['name']} action:",
                        str(action1),
                        "",
                        f"{rule2['name']} condition:",
                        str(condition2),
                        f"{rule2['name']} action:",
                        str(action2),
                        "",
                        "Combined Z3 result: unsat",
                        "-" * 40,
                        "",
                    ]
                )
            else:
                print(
                    f"No conflict: {rule1['name']} vs "
                    f"{rule2['name']}"
                )
                print(f"Reason: {result['reason']}")

    if not conflicts_only:
        report_lines.append("No conflicts were detected.")

    save_json(
        OUTPUT_DIRECTORY / "formatted_rules.json",
        parsed_rules,
    )

    save_json(
        OUTPUT_DIRECTORY / "variables.json",
        collected_variables,
    )

    save_json(
        OUTPUT_DIRECTORY / "variable_types.json",
        variable_types,
    )

    save_json(
        OUTPUT_DIRECTORY / "z3_rules.json",
        z3_rule_output,
    )

    # Contains every checked pair, including non-conflicting pairs.
    save_json(
        OUTPUT_DIRECTORY / "conflict_results.json",
        conflict_results,
    )

    # Human-readable report showing exactly which rules conflict.
    report_path = OUTPUT_DIRECTORY / "conflict_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    print(f"\nConflict report saved to: {report_path}")


if __name__ == "__main__":
    main()