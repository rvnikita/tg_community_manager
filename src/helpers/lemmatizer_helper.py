import nltk
import os
from nltk.stem import WordNetLemmatizer
import pymorphy2
from langdetect import detect

nltk.data.path.append(
    os.path.join(os.path.dirname(__file__), "nltk_data")
)

def ensure_nltk_corpora():
    try:
        nltk.data.find('corpora/wordnet')
    except LookupError:
        nltk.download('wordnet')
    try:
        nltk.data.find('corpora/omw-1.4')
    except LookupError:
        nltk.download('omw-1.4')

morph = pymorphy2.MorphAnalyzer()
lemmatizer = WordNetLemmatizer()

def get_language(text):
    try:
        return detect(text)
    except Exception:
        return "en"

def lemmatize_words(text):
    lang = get_language(text)
    words = text.lower().split()
    if lang == "ru":
        return set(morph.parse(word)[0].normal_form for word in words)
    elif lang == "en":
        return set(lemmatizer.lemmatize(word) for word in words)
    else:
        return set(words)

def lemmatize_single(trigger):
    lang = get_language(trigger)
    trigger_lower = trigger.lower()
    if lang == "ru":
        return morph.parse(trigger_lower)[0].normal_form
    elif lang == "en":
        return lemmatizer.lemmatize(trigger_lower)
    else:
        return trigger_lower
