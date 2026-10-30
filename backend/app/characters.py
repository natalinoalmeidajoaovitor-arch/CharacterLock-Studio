"""Selectable character profiles and deterministic, model-independent prompt composition."""
from copy import deepcopy

from fastapi import HTTPException

NAMES = ["Sofia Reis", "Lia Costa", "Maya Hart", "Amara Vale", "Noa Bennett", "Elena Mora", "Yuna Park", "Nina Moreau", "Zoe Silva", "Isabel Luna", "Clara Hayes", "Ayla Torres", "Jade Laurent", "Mila Santos", "Iris Chen", "Naomi Rivers", "Leo Martins", "Noah Reed", "Kai Ellis", "Rafael Cruz", "Luca Moretti", "Theo Morgan", "Alex Rivera", "Davi Brooks"]
COUNTRIES = [
    ("BR", "Brasil", "Brazil"), ("PT", "Portugal", "Portugal"), ("US", "Estados Unidos", "the United States"),
    ("CA", "Canadá", "Canada"), ("MX", "México", "Mexico"), ("AR", "Argentina", "Argentina"),
    ("CL", "Chile", "Chile"), ("CO", "Colômbia", "Colombia"), ("PE", "Peru", "Peru"),
    ("UY", "Uruguai", "Uruguay"), ("EC", "Equador", "Ecuador"), ("CR", "Costa Rica", "Costa Rica"),
    ("PA", "Panamá", "Panama"), ("DO", "República Dominicana", "the Dominican Republic"),
    ("GB", "Reino Unido", "the United Kingdom"), ("IE", "Irlanda", "Ireland"), ("FR", "França", "France"),
    ("ES", "Espanha", "Spain"), ("IT", "Itália", "Italy"), ("DE", "Alemanha", "Germany"),
    ("NL", "Países Baixos", "the Netherlands"), ("BE", "Bélgica", "Belgium"), ("CH", "Suíça", "Switzerland"),
    ("AT", "Áustria", "Austria"), ("SE", "Suécia", "Sweden"), ("NO", "Noruega", "Norway"),
    ("DK", "Dinamarca", "Denmark"), ("FI", "Finlândia", "Finland"), ("PL", "Polônia", "Poland"),
    ("CZ", "Chéquia", "Czechia"), ("GR", "Grécia", "Greece"), ("TR", "Turquia", "Türkiye"),
    ("JP", "Japão", "Japan"), ("KR", "Coreia do Sul", "South Korea"), ("CN", "China", "China"),
    ("TW", "Taiwan", "Taiwan"), ("IN", "Índia", "India"), ("ID", "Indonésia", "Indonesia"),
    ("TH", "Tailândia", "Thailand"), ("VN", "Vietnã", "Vietnam"), ("PH", "Filipinas", "the Philippines"),
    ("MY", "Malásia", "Malaysia"), ("SG", "Singapura", "Singapore"), ("AU", "Austrália", "Australia"),
    ("NZ", "Nova Zelândia", "New Zealand"), ("ZA", "África do Sul", "South Africa"), ("NG", "Nigéria", "Nigeria"),
    ("KE", "Quênia", "Kenya"), ("EG", "Egito", "Egypt"), ("MA", "Marrocos", "Morocco"),
    ("AE", "Emirados Árabes Unidos", "the United Arab Emirates"), ("SA", "Arábia Saudita", "Saudi Arabia"),
]


def _field(key, label, choices, default, group, description=""):
    return {"key": key, "label": label, "options": [{"value": value, "label": title, "token": token} for value, title, token in choices], "default": default, "group": group, "description": description}


FIELDS = [
    _field("artistic_name", "Nome artístico", [(name, name, name) for name in NAMES], NAMES[0], "identity", "Escolha um nome para sua personagem fictícia."),
    _field("age", "Idade", [(str(age), f"{age} anos", str(age)) for age in range(18, 81)], "26", "identity", "Somente personagens adultas: de 18 a 80 anos."),
    _field("country", "País de atuação", COUNTRIES, "BR", "identity", "Define o contexto da personagem; a aparência é escolhida separadamente."),
    _field("content_language", "Idioma do conteúdo", [("unspecified", "Definir por produção", ""), ("pt_BR", "Português (Brasil)", "Brazilian Portuguese"), ("pt_PT", "Português (Portugal)", "European Portuguese"), ("en", "Inglês", "English"), ("es", "Espanhol", "Spanish"), ("fr", "Francês", "French"), ("de", "Alemão", "German"), ("it", "Italiano", "Italian"), ("ja", "Japonês", "Japanese"), ("ko", "Coreano", "Korean"), ("zh", "Mandarim", "Mandarin"), ("hi", "Hindi", "Hindi"), ("ar", "Árabe", "Arabic")], "unspecified", "identity", "Preferência editorial independente do país; síntese de voz depende do workflow compatível."),
    _field("presentation", "Apresentação visual", [("feminine", "Feminina", "feminine presentation"), ("masculine", "Masculina", "masculine presentation"), ("androgynous", "Andrógina", "androgynous presentation")], "feminine", "identity"),
    _field("skin_tone", "Tom de pele", [("very_fair", "Muito claro", "very fair"), ("fair", "Claro", "fair"), ("light_medium", "Claro médio", "light-medium"), ("medium_warm", "Médio quente", "warm medium"), ("medium_olive", "Médio oliva", "medium olive"), ("tan", "Bronzeado", "tan"), ("deep_brown", "Castanho profundo", "deep brown"), ("very_deep", "Muito profundo", "very deep")], "medium_warm", "appearance"),
    _field("face", "Formato do rosto", [("oval", "Oval", "oval"), ("round", "Redondo", "round"), ("square", "Quadrado", "square"), ("heart", "Coração", "heart-shaped"), ("diamond", "Diamante", "diamond-shaped"), ("long", "Alongado", "elongated")], "oval", "appearance"),
    _field("distinguishing_features", "Traços marcantes", [("none", "Nenhum selecionado", ""), ("freckles", "Sardas discretas", "subtle freckles"), ("beauty_mark", "Pinta facial discreta", "a subtle facial beauty mark"), ("scar", "Pequena cicatriz facial", "a small facial scar")], "none", "appearance"),
    _field("eye_color", "Cor dos olhos", [("dark_brown", "Castanho escuro", "dark brown"), ("brown", "Castanho", "brown"), ("hazel", "Avelã", "hazel"), ("green", "Verde", "green"), ("blue", "Azul", "blue"), ("gray", "Cinza", "gray"), ("amber", "Âmbar", "amber")], "brown", "appearance"),
    _field("eye_shape", "Formato dos olhos", [("almond", "Amendoados", "almond-shaped"), ("round", "Arredondados", "round"), ("hooded", "Pálpebras encobertas", "hooded"), ("monolid", "Monopálpebra", "monolid"), ("upturned", "Cantos elevados", "upturned"), ("deep_set", "Profundos", "deep-set")], "almond", "appearance"),
    _field("hair_color", "Cor do cabelo", [("black", "Preto", "black"), ("dark_brown", "Castanho escuro", "dark brown"), ("brown", "Castanho", "brown"), ("light_brown", "Castanho claro", "light brown"), ("blonde", "Loiro", "blonde"), ("platinum", "Platinado", "platinum blonde"), ("auburn", "Ruivo acobreado", "auburn"), ("red", "Ruivo", "red"), ("gray", "Grisalho", "gray"), ("white", "Branco", "white"), ("pastel_pink", "Rosa pastel", "pastel pink"), ("blue", "Azul", "blue")], "dark_brown", "appearance"),
    _field("hair_length", "Comprimento do cabelo", [("shaved", "Raspado", "shaved"), ("very_short", "Muito curto", "very short"), ("short", "Curto", "short"), ("chin", "Na altura do queixo", "chin-length"), ("shoulder", "Na altura dos ombros", "shoulder-length"), ("long", "Longo", "long"), ("very_long", "Muito longo", "very long")], "long", "appearance"),
    _field("hair_texture", "Textura do cabelo", [("straight", "Liso", "straight"), ("wavy", "Ondulado", "wavy"), ("curly", "Cacheado", "curly"), ("coily", "Crespo", "coily")], "wavy", "appearance"),
    _field("hair_style", "Penteado", [("loose", "Solto", "worn loose"), ("center_part", "Dividido ao meio", "center-parted"), ("side_part", "Dividido de lado", "side-parted"), ("ponytail", "Rabo de cavalo", "in a ponytail"), ("bun", "Coque", "in a bun"), ("braids", "Tranças", "in braids"), ("locs", "Locs", "in locs"), ("bob", "Bob", "in a bob cut"), ("pixie", "Pixie", "in a pixie cut"), ("natural", "Natural", "in a natural style")], "loose", "appearance"),
    _field("body_type", "Tipo de corpo", [("balanced", "Proporções equilibradas", "balanced body proportions"), ("slim", "Esbelto", "slim build"), ("athletic", "Atlético", "athletic build"), ("curvy", "Curvilíneo", "curvy build"), ("broad", "Estrutura ampla", "broad build"), ("stocky", "Estrutura robusta", "stocky build")], "balanced", "appearance"),
    _field("height", "Altura", [(f"{height}_cm", f"{height} cm", f"{height} cm tall") for height in range(145, 201, 5)], "170_cm", "appearance"),
    _field("makeup", "Maquiagem", [("none", "Sem maquiagem", "no makeup"), ("natural", "Natural", "natural makeup"), ("soft_glam", "Glamour suave", "soft glam makeup"), ("editorial", "Editorial", "editorial makeup"), ("bold", "Marcante", "bold makeup with defined eyes")], "natural", "style"),
    _field("wardrobe", "Figurino", [("casual", "Casual contemporâneo", "contemporary casual clothing"), ("minimal", "Minimalista", "minimalist neutral clothing"), ("streetwear", "Streetwear", "streetwear clothing"), ("business", "Executivo", "tailored business clothing"), ("sport", "Esportivo", "athletic clothing"), ("elegant", "Elegante", "elegant evening clothing"), ("bohemian", "Boêmio", "bohemian clothing"), ("vintage", "Vintage", "vintage-inspired clothing"), ("creative", "Criativo e colorido", "colorful creative clothing")], "casual", "style"),
    _field("accessories", "Acessórios", [("none", "Sem acessórios", "no accessories"), ("minimal_jewelry", "Joias discretas", "minimal jewelry"), ("earrings", "Brincos", "small earrings"), ("glasses", "Óculos de grau", "eyeglasses"), ("sunglasses", "Óculos de sol", "sunglasses"), ("watch", "Relógio", "a wristwatch"), ("hat", "Chapéu", "a hat"), ("necklace", "Colar", "a simple necklace")], "minimal_jewelry", "style"),
    _field("personality", "Personalidade", [("warm", "Acolhedora", "warm and approachable"), ("confident", "Confiante", "confident and composed"), ("playful", "Divertida", "playful and expressive"), ("calm", "Calma", "calm and thoughtful"), ("energetic", "Energética", "energetic and outgoing"), ("creative", "Criativa", "creative and curious"), ("sophisticated", "Sofisticada", "sophisticated and poised"), ("adventurous", "Aventureira", "adventurous and spontaneous")], "warm", "style"),
    _field("content_niche", "Nicho de conteúdo", [("lifestyle", "Estilo de vida", "lifestyle content"), ("fashion", "Moda", "fashion content"), ("beauty", "Beleza", "beauty content"), ("fitness", "Fitness", "fitness content"), ("travel", "Viagens", "travel content"), ("food", "Gastronomia", "food content"), ("technology", "Tecnologia", "technology content"), ("education", "Educação", "educational content"), ("gaming", "Games", "gaming content"), ("music", "Música", "music content"), ("wellness", "Bem-estar", "wellness content"), ("business", "Negócios", "business content")], "lifestyle", "style"),
    _field("photo_style", "Direção visual", [("natural", "Retrato natural", "natural portrait photography with soft daylight"), ("studio", "Estúdio", "professional studio portrait photography with controlled lighting"), ("editorial", "Editorial", "editorial portrait photography"), ("cinematic", "Cinematográfico", "cinematic portrait photography with deliberate lighting"), ("ugc", "UGC espontâneo", "candid UGC-style photography with realistic everyday lighting"), ("film", "Analógico", "film-inspired portrait photography with subtle grain")], "natural", "style"),
]
FIELD_INDEX = {field["key"]: field for field in FIELDS}
DEFAULTS = {field["key"]: field["default"] for field in FIELDS}
SECTION_LABELS = {"identity": "Identidade e origem", "appearance": "Aparência", "style": "Estilo e presença"}


def catalog() -> dict:
    fields = [{**{key: value for key, value in field.items() if key != "options"}, "options": [{"value": option["value"], "label": option["label"]} for option in field["options"]]} for field in FIELDS]
    return {"version": 1, "names": list(NAMES), "fields": fields, "sections": [{"id": group, "label": label, "fields": [deepcopy(field) for field in fields if field["group"] == group]} for group, label in SECTION_LABELS.items()], "defaults": dict(DEFAULTS)}


def normalize_attributes(attributes: dict[str, str], existing: dict[str, str] | None = None) -> dict[str, str]:
    unknown = sorted(set(attributes) - set(FIELD_INDEX))
    if unknown:
        raise HTTPException(422, {"message": "Característica não reconhecida no catálogo", "fields": unknown})
    selected = DEFAULTS | (existing or {}) | attributes
    for key, value in selected.items():
        if key not in FIELD_INDEX or not isinstance(value, str) or value not in {option["value"] for option in FIELD_INDEX[key]["options"]}:
            raise HTTPException(422, {"message": "Selecione uma opção válida do catálogo", "field": key, "value": value})
    return selected


def compose_profile(attributes: dict[str, str], name: str | None = None) -> tuple[str, str, str]:
    """Compose from explicit choices only; country never infers physical traits."""
    name = name or attributes["artistic_name"]
    options = {key: next(option for option in FIELD_INDEX[key]["options"] if option["value"] == value) for key, value in attributes.items()}
    token = {key: option["token"] for key, option in options.items()}
    label = {key: option["label"] for key, option in options.items()}
    description = (f"Personagem virtual fictícia: {name}, {label['age']}, com atuação em {label['country']}. "
                   f"Apresentação {label['presentation'].lower()}; olhos {label['eye_color'].lower()}, cabelo {label['hair_color'].lower()}, "
                   f"{label['hair_length'].lower()} e {label['hair_texture'].lower()}. "
                   f"Figurino {label['wardrobe'].lower()}; personalidade {label['personality'].lower()}. "
                   f"Conteúdo: {label['content_niche'].lower()}. Visual: {label['photo_style'].lower()}.")
    prompt = (f"An original fictional adult virtual character named {name}, {token['age']} years old, based in {token['country']}, with {token['presentation']}. "
              f"Appearance: {token['skin_tone']} skin; {token['face']} face; {token['eye_shape']} {token['eye_color']} eyes; "
              f"{token['hair_length']}, {token['hair_texture']}, {token['hair_color']} hair {token['hair_style']}; "
              f"{token['body_type']}; {token['height']}. "
              f"{('Distinguishing features: ' + token['distinguishing_features'] + '. ') if token['distinguishing_features'] else ''}"
              f"Styling: {token['makeup']}, {token['wardrobe']}, {token['accessories']}. "
              f"Personality: {token['personality']}. Content focus: {token['content_niche']}. "
              f"{('Preferred content language: ' + token['content_language'] + '. ') if token['content_language'] else ''}"
              f"Visual direction: {token['photo_style']}. Maintain a consistent facial identity and recognizable proportions across views.")
    return name, description, prompt
