import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as px
from plotly import tools
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['Hyperopt_MRE_validierung_higherC_border_test']

trail = db.Trail_number_1

test_data = trail.find_one({"Name": "Test"})
fig, ax = plt.subplots(nrows=2, ncols=1, figsize=(10, 10))
ax1, ax2 = ax.flatten()
ts = 1e-4  # if ts stored: take from db
t = np.arange(0, len(test_data['lc_capacitor1_v']) * ts, ts).tolist()

df2 = pd.DataFrame(t)
df2['t'] = pd.DataFrame(t)
df2['v_a'] = pd.DataFrame(test_data['lc_capacitor1_v'])
df2['v_b'] = pd.DataFrame(test_data['lc_capacitor2_v'])
df2['v_c'] = pd.DataFrame(test_data['lc_capacitor3_v'])

df2['v_a_SP'] = pd.DataFrame(test_data['inverter1_v_ref_0'])

x = df2['t']
v_a = df2['v_a']
v_b = df2['v_b']
v_c = df2['v_c']
v_a_SP = df2['v_a_SP']

# df2['v_a'] = pd.DataFrame(test_data['lc_inductor1_i'])
# df2['v_b'] = pd.DataFrame(test_data['lc_inductor2_i'])
# df2['v_c'] = pd.DataFrame(test_data['lc_inductor3_i'])
# df2['v_a_SP'] = pd.DataFrame(test_data['master_SPVa'])
# df2['v_b_SP'] = pd.DataFrame(test_data['master_SPVb'])
# df2['v_c_SP'] = pd.DataFrame(test_data['master_SPVc'])
# #
# v_b_SP = df2['v_b_SP']
# v_c_SP = df2['v_c_SP']

# plot = px.Figure(data=[px.Scatter(
#    x=x,
#    y=y,
#    mode='lines', )
# ])


"""
plot = tools.make_subplots(rows=1, cols=2, specs=[[{}, {}]], shared_xaxes=True,
                          shared_yaxes=False, vertical_spacing=0.001)

plot.add_trace(
    px.Scatter(x=x, y=v_a),1,1)


plot.add_trace(
    px.Scatter(x=x, y=v_b),1,2)

plot.add_trace(
    px.Scatter(x=x, y=v_c),1,2)

plot.add_trace(
    px.Scatter(x=x, y=v_a_SP),1,1)
"""

plot = px.Figure()
plot.add_trace(
    px.Scatter(x=x, y=v_a))

plot.add_trace(
    px.Scatter(x=x, y=v_b))

plot.add_trace(
    px.Scatter(x=x, y=v_c))

plot.add_trace(
    px.Scatter(x=x, y=v_a_SP))

# plot.add_trace(
#    px.Scatter(x=x, y=v_b_SP))

# plot.add_trace(
#    px.Scatter(x=x, y=v_c_SP))

plot.update_layout(
    xaxis=dict(
        rangeselector=dict(
            buttons=list([
                dict(count=1,
                     step="day",
                     stepmode="backward"),
            ])
        ),
        rangeslider=dict(
            visible=True
        ),
    )
)

plot.show()