import pandas as pd


def generate_seed(relays_url_csv_path, relays_seed_csv_path):
    relays_url = pd.read_csv(relays_url_csv_path)
    relays_url['domain'] = relays_url['relay_url'].apply(
        lambda x: 'wss://'+x.split("/")[2])
    groups = relays_url.groupby(['domain'])
    relays_seed = {'relay_url': [], 'count': []}
    for domain, group in groups:
        if group.shape[0] == 1:
            relay_url = group.iloc[0]['relay_url']
        else:
            relay_url = group[group['count'] ==
                              group['count'].max()].iloc[0]['relay_url']
        count = int(group['count'].sum())
        relays_seed['relay_url'].append(relay_url)
        relays_seed['count'].append(count)

    relays_seed = pd.DataFrame.from_dict(relays_seed)
    relays_seed = relays_seed.sort_values(by='count', ascending=False)
    relays_seed.to_csv(relays_seed_csv_path, index=False)


if __name__ == '__main__':
    relays_url_csv_path = 'relays_url.csv'
    relays_seed_csv_path = 'relays_seed.csv'
    generate_seed(relays_url_csv_path, relays_seed_csv_path)
