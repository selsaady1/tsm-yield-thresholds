from common import TARGET, dump, frozen, recorded

if __name__ == "__main__":
    with recorded("baseline") as folder:
        result = frozen.run_experiment(frozen.FrozenInstance.step1_baseline(), "TSMF")
        values = {key: result[key] for key in TARGET}
        dump(folder / "values.json", values)
        print(values, flush=True)
        if any(format(values[k], ".2f") != ref for k, ref in TARGET.items()):
            raise SystemExit("STOP: frozen RP, EEV or VSS differs from target at cent precision.")

