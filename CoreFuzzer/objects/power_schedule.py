# modified from https://www.fuzzingbook.org/html/GreyboxFuzzer.html
from collections.abc import Sequence
from typing import List
import random

class Seed:
    """Represent an input with additional attributes"""

    def __init__(self) -> None:
        self.energy = 1.0
        self.adjusted_energy = 1.0
        self.count = 0

    def addEnergy(self, energy) -> None:
        self.energy += energy

class PowerSchedule:
    """Define how fuzzing time should be distributed across the population."""
    def __init__(self) -> None:
        """Constructor"""
        pass

    def assignEnergy(self, population: Sequence[Seed]) -> None:
        """Assigns each seed the same energy"""
        for seed in population:
            seed.energy = 1.0
            seed.adjusted_energy = 1.0
    
    # calculate the adjusted energy for each seed
    def adjustEnergy(self, population: Sequence[Seed]) -> None:
        """Calculate the adjusted energy for each seed"""
        least_energy = 9999
        total_count = 0
        for seed in population:
            total_count += seed.count
            if seed.energy < least_energy:
                least_energy = seed.energy
            seed.adjusted_energy = seed.energy # initialize adjusted energy
            
        for seed in population:
            # assign more energy to less visited states
            if seed.count < (total_count / len(population)):
                seed.adjusted_energy = seed.energy + 1
            # max energy is 10 times of least energy
            if seed.energy > least_energy * 10:
                seed.adjusted_energy = least_energy * 10

    def normalizedEnergy(self, population: Sequence[Seed]) -> List[float]:
        """Normalize energy"""
        energy = list(map(lambda seed: seed.adjusted_energy, population))
        print("energy:", energy)
        sum_energy = sum(energy)  # Add up all values in energy
        assert sum_energy != 0
        norm_energy = list(map(lambda nrg: nrg / sum_energy, energy))
        return norm_energy

    def choose(self, population: Sequence[Seed]) -> Seed:
        """Choose weighted by normalized energy."""
        norm_energy = self.normalizedEnergy(population)
        seed: Seed = random.choices(population, weights=norm_energy)[0]
        return seed