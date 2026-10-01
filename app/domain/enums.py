from enum import StrEnum


class Origin(StrEnum):
    Human = "Human"
    Mutant = "Mutant"
    Alien = "Alien"
    Robot = "Robot"
    Radiation = "Radiation"
    GodEternal = "GodEternal"
    Animal = "Animal"
    Cosmic = "Cosmic"
    Infection = "Infection"
    Other = "Other"


class PowerFamily(StrEnum):
    Strength = "Strength"
    Flight = "Flight"
    Speed = "Speed"
    Mind = "Mind"
    Energy = "Energy"
    Magic = "Magic"
    AgilityCombat = "AgilityCombat"
    Healing = "Healing"
    Shapeshifting = "Shapeshifting"
    TechGadgets = "TechGadgets"


class Team(StrEnum):
    Avengers = "Avengers"
    XMen = "XMen"
    FantasticFour = "FantasticFour"
    Guardians = "Guardians"
    Shield = "Shield"
    Defenders = "Defenders"
    Solo = "Solo"


class Style(StrEnum):
    Science = "Science"
    Humor = "Humor"
    Leadership = "Leadership"
    Loner = "Loner"
    Dark = "Dark"
    Idealist = "Idealist"
    Rebel = "Rebel"
    Strategist = "Strategist"


class Choice(StrEnum):
    PASS = "PASS"
    ASSEMBLE = "ASSEMBLE"


class Author(StrEnum):
    USER = "USER"
    CHARACTER = "CHARACTER"


class Category(StrEnum):
    """Categorias de `whyYouMatch`, na ordem Origin → Powers → Teams → Style."""

    origin = "origin"
    powers = "powers"
    teams = "teams"
    style = "style"
