"""Neighbouring areas per city, so one search can cover "Islington and just beyond".

Each area lists its neighbours, nearest first. Every restaurant's area must appear here
(checked by tests). Lookups are case-insensitive.
"""

from __future__ import annotations

NEARBY: dict[str, dict[str, list[str]]] = {
    "london": {
        "Islington": ["Highbury", "Angel", "Clerkenwell", "King's Cross", "Shoreditch", "Dalston", "Camden"],
        "Highbury": ["Islington", "Angel", "Dalston", "King's Cross"],
        "Angel": ["Islington", "Clerkenwell", "King's Cross", "Highbury", "Shoreditch"],
        "Clerkenwell": ["Angel", "Islington", "City of London", "St Paul's", "Shoreditch", "King's Cross"],
        "King's Cross": ["Angel", "Islington", "Camden", "Clerkenwell", "Fitzrovia"],
        "Camden": ["King's Cross", "Hampstead", "Islington", "Fitzrovia"],
        "Hampstead": ["Camden", "Highbury"],
        "Shoreditch": ["Hackney", "Dalston", "City of London", "Clerkenwell", "Angel", "Islington"],
        "Hackney": ["Dalston", "Shoreditch", "Islington"],
        "Dalston": ["Hackney", "Highbury", "Islington", "Shoreditch"],
        "City of London": ["St Paul's", "Clerkenwell", "Shoreditch", "Borough", "South Bank"],
        "St Paul's": ["City of London", "Clerkenwell", "South Bank", "Borough", "Covent Garden"],
        "Borough": ["South Bank", "City of London", "St Paul's"],
        "South Bank": ["Borough", "Covent Garden", "St Paul's", "City of London"],
        "Covent Garden": ["Soho", "South Bank", "Fitzrovia", "St Paul's", "Mayfair"],
        "Soho": ["Covent Garden", "Fitzrovia", "Mayfair", "Marylebone"],
        "Fitzrovia": ["Soho", "Marylebone", "Covent Garden", "King's Cross"],
        "Marylebone": ["Fitzrovia", "Mayfair", "Soho"],
        "Mayfair": ["Marylebone", "Soho", "Covent Garden", "Chelsea"],
        "Chelsea": ["Kensington", "Battersea", "Mayfair"],
        "Kensington": ["Chelsea", "Notting Hill"],
        "Notting Hill": ["Kensington", "Marylebone"],
        "Battersea": ["Clapham", "Chelsea"],
        "Clapham": ["Battersea", "Brixton"],
        "Brixton": ["Clapham", "Battersea"],
    },
    "paris": {
        "Le Marais": ["Bastille", "Canal Saint-Martin", "Opéra"],
        "Bastille": ["Le Marais", "Canal Saint-Martin", "Belleville"],
        "Canal Saint-Martin": ["Belleville", "Le Marais", "Bastille", "South Pigalle"],
        "Belleville": ["Canal Saint-Martin", "Bastille"],
        "Opéra": ["South Pigalle", "Le Marais", "Saint-Germain-des-Prés"],
        "South Pigalle": ["Montmartre", "Opéra", "Canal Saint-Martin"],
        "Montmartre": ["South Pigalle", "Opéra"],
        "Saint-Germain-des-Prés": ["Opéra", "Le Marais"],
    },
    "new_york": {
        "West Village": ["Chelsea", "Tribeca", "Flatiron", "East Village"],
        "Chelsea": ["West Village", "Flatiron", "Midtown"],
        "Flatiron": ["Gramercy", "Chelsea", "West Village", "East Village"],
        "Gramercy": ["Flatiron", "East Village", "Midtown"],
        "East Village": ["Lower East Side", "Gramercy", "West Village", "Flatiron"],
        "Lower East Side": ["East Village", "Tribeca", "Williamsburg"],
        "Tribeca": ["West Village", "Lower East Side"],
        "Midtown": ["Chelsea", "Gramercy", "Upper East Side", "Upper West Side"],
        "Upper East Side": ["Midtown", "Upper West Side"],
        "Upper West Side": ["Midtown", "Upper East Side"],
        "Williamsburg": ["Lower East Side", "East Village"],
        "Carroll Gardens": ["Lower East Side", "Tribeca"],
        "Flushing": ["Williamsburg"],
    },
    "los_angeles": {
        "Santa Monica": ["Venice", "Sawtelle", "Pacific Palisades"],
        "Venice": ["Santa Monica", "Sawtelle"],
        "Pacific Palisades": ["Santa Monica"],
        "Sawtelle": ["Santa Monica", "Beverly Hills", "Venice"],
        "Beverly Hills": ["West Hollywood", "Sawtelle", "Koreatown"],
        "West Hollywood": ["Beverly Hills", "Hollywood"],
        "Hollywood": ["West Hollywood", "Los Feliz", "Silver Lake", "Koreatown"],
        "Los Feliz": ["Silver Lake", "Hollywood"],
        "Silver Lake": ["Los Feliz", "Hollywood", "Downtown"],
        "Koreatown": ["Downtown", "Hollywood", "Beverly Hills"],
        "Downtown": ["Arts District", "Koreatown", "Boyle Heights", "Silver Lake"],
        "Arts District": ["Downtown", "Boyle Heights"],
        "Boyle Heights": ["Arts District", "Downtown"],
        "Pasadena": ["Silver Lake", "Los Feliz"],
        "Artesia": ["Downtown"],
    },
}


def nearby_areas(city: str | None, area: str) -> list[str]:
    """Neighbours of ``area`` (nearest first), across one city or all of them when city is None."""
    wanted = area.strip().lower()
    for city_id, areas in NEARBY.items():
        if city and city_id != city:
            continue
        for name, neighbours in areas.items():
            if name.lower() == wanted:
                return neighbours
    return []
