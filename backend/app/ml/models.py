# backend/app/ml/models.py

class BlendedRegressor:
    """
    A simple stacked regressor blending KernelRidge and LightGBM.
    """
    def __init__(self, krr_pipeline, lgb_model=None):
        self.krr_pipeline = krr_pipeline
        self.lgb_model = lgb_model

    def fit(self, X, y):
        self.krr_pipeline.fit(X, y)
        if self.lgb_model is not None:
            self.lgb_model.fit(X, y, eval_set=[(X, y)], eval_metric="l2")
        return self

    def predict(self, X):
        pred_krr = self.krr_pipeline.predict(X)
        if self.lgb_model is None:
            return pred_krr
        pred_lgb = self.lgb_model.predict(X)
        return 0.5 * pred_krr + 0.5 * pred_lgb
