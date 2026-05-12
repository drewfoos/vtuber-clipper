from clipper.util.slug import slugify

def test_slugify_basic():
    assert slugify("HOLY NO WAY") == "holy-no-way"

def test_slugify_punctuation():
    assert slugify("I can't believe it!") == "i-cant-believe-it"

def test_slugify_trims_to_max_length():
    long = "a" * 100
    assert len(slugify(long, max_len=60)) == 60

def test_slugify_handles_unicode():
    assert slugify("café — résumé") == "cafe-resume"

def test_slugify_index_prefix():
    assert slugify("hello", index=3) == "03_hello"
