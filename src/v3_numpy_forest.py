"""Bounded deterministic NumPy random forest for offline V3 research.

Bootstrap shallow classification trees with random feature subsets, Gini
splits over fixed quantile candidates and smoothed leaf probabilities.
Not an optimized general-purpose forest or calibrated probability model.
"""
from __future__ import annotations

import math
import numpy as np

FOREST_RECIPE = dict(trees=24,max_depth=4,min_leaf=10,
                     bootstrap_cap=4096,quantiles=[0.25,0.5,0.75],
                     seed=20261126,leaf_pseudocount=1,
                     feature_subset="ceil_sqrt",split="gini")


def fit_forest(X,y):
    """Inputs are validated, chronologically purged training arrays."""
    rng=np.random.default_rng(FOREST_RECIPE["seed"])
    n,d=X.shape
    mtry=max(1,math.ceil(math.sqrt(d)))
    leaf=FOREST_RECIPE["min_leaf"]

    def build(indices,depth):
        labels=y[indices]
        positives=float(labels.sum())
        size=len(indices)
        node={"p":(positives+1)/(size+2)}
        if depth>=FOREST_RECIPE["max_depth"] or size<2*leaf or positives in (0,size):
            return node
        p=positives/size
        best_gain=0.0
        best=None
        for j in sorted(rng.choice(d,size=mtry,replace=False).tolist()):
            v=X[indices,j]
            thresholds=np.unique(np.quantile(v,FOREST_RECIPE["quantiles"]))
            for t in thresholds:
                mask=v<=t
                count=int(mask.sum())
                if count<leaf or size-count<leaf:
                    continue
                pl=float(labels[mask].sum())/count
                pr=(positives-pl*count)/(size-count)
                gain=2*p*(1-p)-(count*2*pl*(1-pl)+(size-count)*2*pr*(1-pr))/size
                if gain>best_gain+1e-12:
                    best_gain=gain
                    best=(j,float(t),indices[mask],indices[~mask])
        if best is None:
            return node
        j,t,left,right=best
        node.update(feature=j,threshold=t,left=build(left,depth+1),right=build(right,depth+1))
        return node

    return [build(rng.integers(0,n,size=min(n,FOREST_RECIPE["bootstrap_cap"])),0)
            for _ in range(FOREST_RECIPE["trees"])]


def forest_probability(trees,x):
    def predict(node):
        while "feature" in node:
            node=node["left"] if x[node["feature"]]<=node["threshold"] else node["right"]
        return node["p"]
    return math.fsum(predict(tree) for tree in trees)/len(trees)
