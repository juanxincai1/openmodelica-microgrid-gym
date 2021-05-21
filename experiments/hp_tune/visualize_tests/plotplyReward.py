import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as px
from plotly import tools
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['Master_V_ctrl_dq0_DDPG_without_current_no_Delay']

trail = db.Trail_number_1

test_data = trail.find_one({"Name": "Test"})
# fig, ax = plt.subplots(nrows=2, ncols=1, figsize=(10, 10))
# ax1, ax2 = ax.flatten()
ts = 1e-4  # if ts stored: take from db
t = np.arange(0, len(test_data['Reward']) * ts, ts).tolist()

df2 = pd.DataFrame(t)
df2['t'] = pd.DataFrame(t)
df2['r'] = pd.DataFrame(test_data['Reward'])

x = df2['t']
v_a = df2['r']

plt.plot(x, v_a)
plt.xlabel('Time')
plt.ylabel('Reward')
plt.grid()
plt.show()

# v_a_SP = df2['v_a_SP']

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

# plot.add_trace(
#    px.Scatter(x=x, y=v_a_SP))

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