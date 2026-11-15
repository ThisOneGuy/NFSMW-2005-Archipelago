CUSTOMIZABLE_CARS = [
    "Aston Martin DB9",
    "Audi A3 3.2 quattro",
    "Audi A4 3.2 FSI quattro",
    "Audi TT 3.2 quattro",
    "Cadillac CTS",
    "Chevrolet Cobalt SS",
    "Chevrolet Corvette C6",
    "Dodge Viper SRT-10",
    "Fiat Punto",
    "Ford GT",
    "Ford Mustang GT",
    "Lamborghini Gallardo",
    "Lamborghini Murciélago",
    "Lexus IS 300",
    "Lotus Elise",
    "Mazda RX-7",
    "Mazda RX-8",
    "Mercedes-Benz CLK 500",
    "Mercedes-Benz SL 500",
    "Mercedes-Benz SLR McLaren",
    "Mitsubishi Eclipse GT",
    "Mitsubishi Lancer Evolution VIII",
    "Pontiac GTO",
    "Porsche 911 Carrera S",
    "Porsche 911 Turbo S",
    "Porsche Carrera GT",
    "Porsche Cayman S",
    "Renault Clio V6",
    "Subaru Impreza WRX STi",
    "Toyota Supra",
    "Vauxhall Monaro VXR",
    "Volkswagen Golf GTI",
]

SPECIAL_CARS = ["BMW M3 GTR (E46)"]

VANILLA_DEALERSHIP_UNLOCK = {
    "Aston Martin DB9": 7,
    "Audi A3 3.2 quattro": 15,
    "Audi A4 3.2 FSI quattro": 14,
    "Audi TT 3.2 quattro": 15,
    "Cadillac CTS": 12,
    "Chevrolet Cobalt SS": 16,
    "Chevrolet Corvette C6": 5,
    "Dodge Viper SRT-10": 6,
    "Fiat Punto": 16,
    "Ford GT": 4,
    "Ford Mustang GT": 12,
    "Lamborghini Gallardo": 6,
    "Lamborghini Murciélago": 4,
    "Lexus IS 300": 16,
    "Lotus Elise": 8,
    "Mazda RX-7": 9,
    "Mazda RX-8": 12,
    "Mercedes-Benz CLK 500": 8,
    "Mercedes-Benz SL 500": 11,
    "Mercedes-Benz SLR McLaren": 3,
    "Mitsubishi Eclipse GT": 14,
    "Mitsubishi Lancer Evolution VIII": 11,
    "Pontiac GTO": 10,
    "Porsche 911 Carrera S": 7,
    "Porsche 911 Turbo S": 5,
    "Porsche Carrera GT": 3,
    "Porsche Cayman S": 10,
    "Renault Clio V6": 13,
    "Subaru Impreza WRX STi": 9,
    "Toyota Supra": 13,
    "Vauxhall Monaro VXR": 10,
    "Volkswagen Golf GTI": 16,
    "BMW M3 GTR (E46)": 1,
}


def logic_cars_for_blacklist(rank):
    if not 1 <= rank <= 15:
        return ()
    threshold = max(3, rank + 1)
    return tuple(
        car
        for car, unlocked_after in VANILLA_DEALERSHIP_UNLOCK.items()
        if unlocked_after <= threshold
    )
