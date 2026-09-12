const twitterOptionalCookies = ['__cf_bm', '__cuid', 'gt', 'guest_id', 'guest_id_ads', 'guest_id_marketing', 'personalization_id'];
export default [
  // Upstream optional cookies; use only when the live field omits both flags.
  // https://github.com/mautrix/meta/blob/857f87f7f57d1a036550d77116def663a061c541/pkg/messagix/cookies/cookies.go
  {"id":"instagram","name":"Instagram","domains":["instagram.com"],"optionalSources":{"cookie":["rur","shbid","shbts","mid","ig_did"]}},
  {"id":"facebook","name":"Facebook / Messenger","domains":["facebook.com","messenger.com"]},
  {"id":"linkedin","name":"LinkedIn","domains":["linkedin.com"]},
  // Optional inputs in the upstream browser challenge step. Core authentication
  // and its first challenge token/user-agent are not in these defaults.
  // https://github.com/mautrix/twitter/blob/975e471a8c6fd9b72ed60f0ee0a9484e0359240a/pkg/connector/login.go
  {"id":"twitter","name":"X / Twitter","domains":["x.com","twitter.com"],"optionalSources":{
    "cookie":twitterOptionalCookies,
    "request_header":["sec-ch-ua","sec-ch-ua-platform","sec-ch-ua-mobile"],
    "local_storage":[...Array.from({length:7}, (_, i) => `fi.mau.twitter.castle_token_${i + 2}`),
      ...twitterOptionalCookies.map(name => `fi.mau.twitter.cookie.${name}`)]
  }},
  {"id":"discord","name":"Discord","domains":["discord.com","discordapp.com"]},
  {"id":"slack","name":"Slack","domains":["slack.com"]}
];
