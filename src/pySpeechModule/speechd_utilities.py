import xml.etree.ElementTree as ET
import logging

def hdlc_escape(data: bytes) -> bytes:
    """
    hdlc_escape is for excaping newline chars using hdlc encoding. 
    This function likely has little value to the users but is need internally.
    
    :meta private:
    """
    ESCAPE = 0x7D
    INVERT = 1 << 5
    out = bytearray()

    for byte in data:
        if byte == ESCAPE or byte == ord("\n"):
            out.append(ESCAPE)
            out.append(byte ^ INVERT)
        else:
            out.append(byte)

    return bytes(out)

def parse_ssml(data: bytes) -> list[dict]:
    """
    This is a convenience function for parsing SSML into a list of dicts in the format

    .. code-block:: python

        [{"mark": "<mark>", "text": "<text>"}]

    :param data: The bytes string for your SSML text
    :type bytes: bytes
    :return: List of dicts each with mark and text
    :rtype: list
    """

    output = []
    buffer = []

    # Parse the SSML XML data
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        logging.error("parse_ssml: Failed to parse XML")
        return output

    # Handle text directly inside <speak> before any child elements
    if root.text:
        buffer.append(root.text)

    # Iterate through direct child elements of <speak>
    for child in root:
        # Check for <mark> element
        if child.tag.endswith("mark"):
            mark_name = child.attrib.get("name", "")

            output.append(
                {"mark": mark_name, "text": "".join(buffer)}
            )

            # Reset buffer after encountering a mark
            buffer.clear()

        # Append trailing text after a child node (XML tail text)
        if child.tail:
            buffer.append(child.tail)

    # Add any remaining trailing text after the final mark
    if buffer:
        output.append({"mark": "", "text": "".join(buffer)})

    return output

def strip_ssml(ssml_string: bytes):
    """
    This is a convenience function for stripping out all SSML tags leaving just the text.

    :param data: The bytes string for your SSML text
    :type bytes: bytes
    :return: extracted text
    :rtype: string
    """

    # Wrap in a root element if the string is an XML fragment
    try:
        root = ET.fromstring(ssml_string)
    except ET.ParseError:
        # Wrap fragments in a temporary root node to ensure valid parsing
        root = ET.fromstring(f"<root>{ssml_string}</root>")
    
    # itertext() yields all text within the element and its children
    return "".join(root.itertext())