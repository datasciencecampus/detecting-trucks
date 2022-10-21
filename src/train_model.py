"""
Train the classification model from some set of training data.

Can be executed in two modes with respect to training data sources:
1) Using the pre-supplied training data generated from an analysis of roads in
Nairobi, Kenya.
2) Using the custom made training data generated by working through the building
of training data process (see walkthrough in the documentation and script
'build_training_data.py'.

Script can also perform some model evaluation, namely by executing a  K-fold
cross validation, and return a AUCPR visual.
"""

# Standard Library
import pickle
from pathlib import Path

## Third Party
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from imblearn.ensemble import BalancedRandomForestClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import auc, classification_report, precision_recall_curve
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.utils import shuffle

# Project
from utils.column_headers import define_training_data_column_headers
from utils.file_handling import set_data_dir
from yaml import Loader, load


def read_training_features(
    location: str,
    use_custom_training_data: bool = True,
) -> pd.DataFrame:
    """
    Read in training features from either pre-supplied or user generated training data.

    Parameters
    ----------
    location_name : str
        String representation of location of interest, as used on file naming.
    use_custom_training_data : bool, optional
        If False, pre-supplied training data used for modelling. If True, user
        generated training data is used from the build_training_data.py script.
        Training based on imagery from the location of interest is recommended,
        but pre-supplied is useful for test runs. The default is True.

    Returns
    -------
    pd.DataFrame
        Dataframe of training data (i.e. dataframe of feature values labelled
        as either truck or non-truck)

    """
    if not use_custom_training_data:
        training_data_filepath = (
            Path(__file__)
            .resolve()
            .parent.parent.joinpath("data", "preprepared_training_data")
        )
        features = pd.read_csv(
            training_data_filepath.joinpath("nairobi_training_features.csv")
        )
        more_features = pd.read_csv(
            training_data_filepath.joinpath("nairobi2_training_features.csv")
        )
        train_features = pd.concat([features, more_features])
    else:
        training_data = (
            Path(__file__)
            .resolve()
            .parent.parent.joinpath(
                "data",
                location,
                "processed",
                "training",
                location + "_training_features.csv",
            )
        )
        train_features = pd.read_csv(training_data)
    return train_features


def reduce_non_truck_sample(
    features: pd.DataFrame, non_truck_multiple: int = 100
) -> pd.DataFrame:
    """
    Control ratio between number of truck and non-truck positions in training data.

    Parameters
    ----------
    features : pandas.DataFrame
        Dataframe of training data (i.e. dataframe of feature values labelled
        as either truck or non-truck).
    non_truck_multiple : int, optional
        Controls the multiplication factor for truck to non-truck positions.
        For example, the default value of 100 will return a training dataset of
        maximum 100 non-truck pixels for every one truck pixel. The default is 100.

    Returns
    -------
    features : pandas.DataFrame
        Original unaltered dataframe if execution False, or modified dataframe
        if True, where for each row labelled as a truck, there are a maximum of
        non_truck_multiple non-truck rows.

    Notes
    -----
    See technical blog post below for details on the observed effect from
    exploration with various ratios:
    https://datasciencecampus.ons.gov.uk/detecting-trucks-in-east-africa/

    """
    count = lambda x: len(features[features["ml_class"] == x])
    truck_count = count(1)
    non_truck_count = count(0)
    print(f"{truck_count} trucks and {non_truck_count} non-trucks initially.")
    if (non_truck_count / truck_count) > non_truck_multiple:
        max_non_trucks = truck_count * non_truck_multiple
        non_truck_df = features[features["ml_class"] == 0].sample(max_non_trucks)
        features = pd.concat([features[features["ml_class"] == 1], non_truck_df])
    print(f"Downsampling complete: {count(1)} trucks and {count(0)} non-trucks.")
    return features


def model_selection_evaluation(
    outputs_dir: Path,
    features: pd.DataFrame,
    classifier_model: str,
    columns_use: list,
    K: int = 5,
    rf_num_trees: int = 100,
    sample_non_truck_factor: int = None,
):
    """
    Procedure for selecting and evaluating different classifiers.

    Perform K-fold cross validation to evaluate different classification
    model performances, using precision-recall curves.

    Parameters
    ----------
    outputs_dir : Path
        Path to parent output directory where visualizations to be saved.
    features : pd.Dataframe
        Dataframe of feature values in training dataset.
    classifier_model : str
        The classification model to evaluate. Acceptable options are:
        "Random Forest" or "Balanced Random Forest"
    columns_use : list
        A list of features which feed into the classifier model. It is suggested
        to use the full set of features available in the features data frame. But
        this can be modified to select a subset of these features.
    K : int, optional
        The number of folds to be used in stratified K-fold cross-validation.
        The default value is 5.
    rf_num_trees : int, optional
        If using random forest classifiers, defines the number of trees used. The
        default value is 100.
    sample_non_truck_factor : int
        Sets the maximum ratio between truck and non-truck datapoints by
        executing the function reduce_non_truck_sample(). The default value is
        None, in which case the reduce_non_truck_sample function is not executed
        and the default maximum sample of 10,000 non-truck data points is used.

    Returns
    -------
    Generates a precision-recall curve plot and saves image file to "outputs"
    directory.

    Notes
    -----
    Consider experimenting with the number of trees. A value of 100 is likely to
    produce better results, but takes longer to fit and predict than smaller
    numbers.

    """
    if sample_non_truck_factor:
        features = reduce_non_truck_sample(
            features, non_truck_multiple=sample_non_truck_factor
        )

    y = np.array(features["ml_class"])
    X = features[columns_use]
    X, y = shuffle(X, y)
    sc = StandardScaler()
    X = sc.fit_transform(X)

    # Choose cross validation procedure and classifier type
    cv = StratifiedKFold(n_splits=K, shuffle=True, random_state=1)
    if classifier_model == "Random Forest":
        classifier = RandomForestClassifier(n_estimators=rf_num_trees, random_state=99)
    elif classifier_model == "Balanced Random Forest":
        classifier = BalancedRandomForestClassifier(
            n_estimators=rf_num_trees, random_state=99
        )

    mpl.rcParams["axes.linewidth"] = 3
    mpl.rcParams["lines.linewidth"] = 2
    plt.figure(figsize=(18, 13))

    prs, aucs = [], []
    mean_recall = np.linspace(0, 1, 100)

    for i, (train, test) in enumerate(cv.split(X, y)):
        probas_ = classifier.fit(X[train], y[train]).predict_proba(X[test])
        precision, recall, thresholds = precision_recall_curve(y[test], probas_[:, 1])
        prs.append(np.interp(mean_recall, precision, recall))
        pr_auc = auc(recall, precision)
        aucs.append(pr_auc)
        plt.plot(
            recall,
            precision,
            lw=3,
            alpha=0.5,
            label="Fold %d (AUCPR = %0.2f)" % (i + 1, pr_auc),
        )

        y_pred = classifier.predict(X[test])
        print("P.R. AUC =", pr_auc)
        print(classification_report(y[test], y_pred))

    plt.plot([0, 1], [1, 0], linestyle="--", lw=3, color="k", label="Luck", alpha=0.8)
    mean_precision = np.mean(prs, axis=0)
    mean_auc = auc(mean_recall, mean_precision)
    std_auc = np.std(aucs)
    plt.plot(
        mean_precision,
        mean_recall,
        color="navy",
        label=r"Mean (AUCPR = %0.3f $\pm$ %0.2f)" % (mean_auc, std_auc),
        lw=4,
    )

    plt.xlim([-0.05, 1.05])
    plt.ylim([-0.05, 1.05])
    plt.xlabel("Recall", fontweight="bold", fontsize=30)
    plt.ylabel("Precision", fontweight="bold", fontsize=30)
    plt.tick_params(axis="both", which="major", labelsize=20)
    plt.legend(prop={"size": 20}, loc=0)

    # save fig to outputs folder
    plt.savefig(
        outputs_dir.joinpath(
            f"PR_curve_{classifier_model.replace(' ', '_')}_{rf_num_trees}trees"
            f"_{sample_non_truck_factor}nontruckratio.png"
        ),
        dpi=300,
    )
    plt.show()


def train_model(
    outputs_dir: Path,
    features: pd.DataFrame,
    classifier_model: str,
    columns_use: list,
    rf_num_trees: int = 100,
    sample_non_truck_factor: int = None,
):
    """
    Train model with given parameters (adaptable in script).

    Parameters
    ----------
    outputs_dir : pathlib.Path
        Path to parent output directory where model to be saved.
    features : pd.DataFrame
        Dataframe of feature values in training dataset.
    classifier_model : str
        The classification model to be used. Current acceptable options are:
        "Random Forest" or "Balanced Random Forest". However, the function could
        be adapted as desired to experiment with additional models.
    columns_use : list
        A list of features which feed into the classifier model. It is suggested
        to use the full set of features available in the features data frame. But
        this can be modified to select a subset of these features.
    rf_num_trees : int, optional
        If using random forest classifiers, defines the number of trees used. The
        default value is 100.
    sample_non_truck_factor : int, optional
        Sets the maximum ratio between truck and non-truck datapoints by
        executing the function reduce_non_truck_sample(). The default value is
        None, in which case the reduce_non_truck_sample function is not executed
        and the default maximum sample of 10,000 non-truck data points is used.

    Returns
    -------
    model object
        Trained classifier model returned and pickled version saved to file.
    """
    if sample_non_truck_factor:
        features = reduce_non_truck_sample(
            features, non_truck_multiple=sample_non_truck_factor
        )

    y = np.array(features["ml_class"])
    X = features[columns_use]
    X, y = shuffle(X, y)
    sc = StandardScaler()
    X = sc.fit_transform(X)

    # Model selection
    if classifier_model == "Random Forest":
        model = RandomForestClassifier(
            n_estimators=rf_num_trees,
            random_state=99,
        )
    elif classifier_model == "Balanced Random Forest":
        model = BalancedRandomForestClassifier(
            n_estimators=rf_num_trees,
            random_state=99,
        )

    model.fit(X, y)

    model_dir = set_data_dir(outputs_dir, "models")

    with open(model_dir.joinpath("trained_model.pkl"), "wb") as file:
        pickle.dump(model, file)

    # Note: Unnecessary to scale DF for RandomForest, but code in place in case
    # of the use of a different model.
    with open(model_dir.joinpath("scaler.pkl"), "wb") as file:
        pickle.dump(sc, file)


def main(
    location: str = None,
    custom_training: bool = False,
    evaluate_model: bool = False,
):
    outputs_dir = Path(__file__).resolve().parent.parent.joinpath("outputs", location)

    # It is possible to test the model accuracy for different selections of features by
    # selecting subsets of the columns in column_headers list below. All used by default.
    column_headers = define_training_data_column_headers()
    column_headers.remove("validation")

    training_features = read_training_features(
        location,
        use_custom_training_data=custom_training,
    )
    if evaluate_model:
        model_selection_evaluation(
            outputs_dir,
            training_features,
            classifier_model="Random Forest",
            columns_use=column_headers,
            rf_num_trees=100,
            sample_non_truck_factor=100,
        )
    else:
        train_model(
            outputs_dir=outputs_dir,
            features=training_features,
            classifier_model="Random Forest",
            columns_use=column_headers,
            sample_non_truck_factor=100,
        )


def mk_arg_pars():
    """
    Create a comand line arg parse.

    Returns
    -------
    _dict_
        Argparse argument dictionary containing either user inputted args or
        default values extracted from config file.
    """
    import argparse
    from inspect import currentframe, getframeinfo

    filename = getframeinfo(currentframe()).filename
    parent = Path(filename).resolve().parent

    config_file = parent.joinpath("config.yaml")
    params = load(open(config_file), Loader=Loader)

    parser = argparse.ArgumentParser(
        description="Train model using labelled training data."
    )
    parser.add_argument(
        "-l",
        "--location",
        default=params["location"],
        help=(
            "The string representing the location of interest, as used in image"
            " extraction file naming. Defaults to parameter defined in config.yaml ."
        ),
    )
    parser.add_argument(
        "-ct",
        "--custom_training",
        default=False,
        help=(
            "Control whether to read custom, location specific training dataset,"
            " or the included training data from Nairobi. The default is False, "
            "in which case the pre-supplied training data will be used. If True,"
            " the script will expect training data in data/<location>/processed/"
            "training_data/<location>_training_features.csv"
        ),
    )
    parser.add_argument(
        "-eval_model",
        "--evaluate_model",
        default=False,
        help=(
            "Control whether to execute the model evaluation. Will perform a K-fold"
            " cross validation and return a AUCPR visual. Recommended when running "
            "for the first time. The script can be adapted to test performance with"
            " different parameteres and model types."
        ),
    )
    args_pars = parser.parse_args()
    return vars(args_pars)


if __name__ == "__main__":
    run_dict = mk_arg_pars()
    main(**run_dict)
