# Rather than a full fledged parser etc I've done this the lazy way and just 
# used some Regular Expressions to turn JSON5 into JSON. 
# This allows the use of the json module that is available by default.
#
# This gets around serial.py trying to use dpranke's pyjson5 library

import json
import re

# Added to avoid having to use a python version higher than 3.0
# or having to add external dependencies complicating licensing.
def loads(string: str):
    # Remove single-line and multi-line comments
    string = re.sub(r'\/\/.*|\/\*[\s\S]*?\*\/', '', string)
    # Add double quotes to object "key" values
    string = re.sub(r'([a-zA-Z0-9_]+)\s*:', r'"\1":', string)
    # Replace single-quoted strings with double-quoted strings
    string = re.sub(r"'(.*?)'", r'"\1"', string)
    # Get rid of trailing commas
    string = re.sub(r",(?=\s*(?:\]|\)))", '', string)

    return json.loads(string)