import json
import pickle


def save_dict_to_file(data, filename, method='json'):
    """
    Save dictionary to file using specified method

    Args:
        data: Dictionary to save
        filename: Output filename
        method: 'json', 'pickle', 'text', or 'csv'
    """
    try:
        if method == 'json':
            with open(filename, 'w') as file:
                json.dump(data, file, indent=4)

        elif method == 'pickle':
            with open(filename, 'wb') as file:
                pickle.dump(data, file)

        elif method == 'text':
            with open(filename, 'w') as file:
                for key, value in data.items():
                    file.write(f"{key}: {value}\n")

        elif method == 'csv':
            import csv
            with open(filename, 'w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Key", "Value"])
                for key, value in data.items():
                    writer.writerow([key, value])

        else:
            raise ValueError("Method must be 'json', 'pickle', 'text', or 'csv'")

        print(f"Dictionary successfully saved to {filename} using {method}")
        return True

    except Exception as e:
        print(f"Error saving dictionary: {e}")
        return False