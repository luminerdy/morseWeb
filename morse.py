MORSE_CODE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..",
    "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..",
    "9": "----.", "0": "-----",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "!": "-.-.--"
}

REVERSE_CODE = {value: key for key, value in MORSE_CODE.items()}


def text_to_morse(text: str) -> str:
    words = text.upper().split()
    morse_words = []

    for word in words:
        letters = []
        for character in word:
            if character in MORSE_CODE:
                letters.append(MORSE_CODE[character])
        morse_words.append(" ".join(letters))

    return " / ".join(morse_words)


def morse_to_text(morse: str) -> str:
    words = morse.strip().split(" / ")
    decoded_words = []

    for word in words:
        letters = []
        for symbol in word.split():
            letters.append(REVERSE_CODE.get(symbol, "?"))
        decoded_words.append("".join(letters))

    return " ".join(decoded_words)
