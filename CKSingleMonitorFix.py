import configparser

# Define the ranges for variables
RANGES = {
    'cell view x': (0, 1800),
    'render window x': (0, 1800),
    'objectwindow x': (0, 1800)
}

class CaseConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr):
        return optionstr

def check_and_fix_ranges(config_file):
    config = CaseConfigParser()
    config.read(config_file)

    errors = []

    for section in config.sections():
        for key, value in config.items(section):
            print(f"Checking {key} in section {section} with value '{value}'")  # Debugging print statement
            if key in RANGES:
                min_val, max_val = RANGES[key]
                try:
                    original_value = value
                    value = float(value)
                    print(f"Converted value of {key} in section {section}: {value} (range {min_val}-{max_val})")  # Debugging print statement
                    if not (min_val <= value <= max_val):
                        errors.append(f"Error: {key} in section {section} is out of range ({value} not in {min_val}-{max_val}). Setting to 0.")
                        config.set(section, key, '0')
                except ValueError:
                    errors.append(f"Error: {key} in section {section} is not a valid number. Setting to 0.")
                    config.set(section, key, '0')

    with open(config_file, 'w') as configfile:
        config.write(configfile)

    if errors:
        for error in errors:
            print(error)
    else:
        print("All variables are within the specified ranges.")

# Usage
check_and_fix_ranges('CreationKitPrefs.ini')
