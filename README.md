# Highlight bot

It DMs you when certain words are said in certain channels.

## Self hosting

Instructions are for a Debian Linux host. Modify accordingly.

```
$ sudo -u postgres psql
postgres=# CREATE USER bots;
postgres=# CREATE DATABASE highlight WITH OWNER bots;
postgres=# ^D
$ psql highlight -f sql/schema.sql
$ python -m venv .venv
$ . .venv/bin/activate
$ pip install -Ur requirements.txt
$ cp config.example.json5 config.json5
$ # now edit config.json5 accordingly
$ ./bot.py
```

Now copy config.example.json5 to config.json5 and modify it accordingly.

To migrate the database, `pip install migra`, set up a database for staging,
run the new schema file against that database, then just `migra postgresql:///highlight postgresql:///highlight_migrate | psql highlight` for example.

## [License](LICENSE.md)

Most of the documentation is used under the "use my strings idc" license.
Copyright © Rapptz

As for the bot code:

Copyright © @lambda.dance

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You may find a copy of the GNU Affero General Public License
in the [LICENSE.md](LICENSE.md) file in this repository.
