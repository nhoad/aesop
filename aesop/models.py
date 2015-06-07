import os

from peewee import (
    Model, CharField, ForeignKeyField, IntegerField, Proxy, SqliteDatabase,
    BooleanField, IntegrityError, CompositeKey
)

database_proxy = Proxy()
database = None


class BaseModel(Model):
    class Meta:
        database = database_proxy


class Source(BaseModel):
    path = CharField(unique=True)

    # can these work? field name is messed up.
    type = CharField(choices=[
        ('movies', 'Movies'),
        ('tv', 'TV Shows'),
        ('anime', 'Anime'),
    ])


Default = object()


class Config(BaseModel):
    section = CharField()
    key = CharField()
    value = CharField()

    @classmethod
    def get(cls, section, key, default=Default):
        try:
            return cls.get(cls.section == section, cls.key == key).value
        except cls.DoesNotExist:
            if default is not Default:
                cls.create(section=section, key=key, value=str(default))
            return default

    @classmethod
    def create_default(cls):
        pass


class Genre(BaseModel):
    text = CharField(unique=True)

    @classmethod
    def get_or_create(cls, text):
        try:
            return cls.get(cls.text == text)
        except cls.DoesNotExist:
            return cls.create(text=text)


def GenreMixin(join_class):
    class GenreMixin:
        # FIXME: disgusting, won't work across modules
        @property
        def join_class(self):
            return globals()[join_class]

        @property
        def genres(self):
            return Genre.select().join(self.join_class).join(self.__class__).where(
                self.__class__.id == self.id)

        def replace_genres(self, genres):
            self.delete_genres()
            self.add_genres(genres)

        def delete_genres(self):
            q = self.join_class.delete().where(self.join_class.media == self.id)
            q.execute()

        def add_genres(self, genres):
            # FIXME: prevent double ups
            for genre in genres:
                self.join_class.create(media=self, genre=genre)
    return GenreMixin


class Movie(BaseModel, GenreMixin(join_class='MovieGenre')):
    media_id = CharField(unique=True)
    title = CharField()
    path = CharField()
    year = IntegerField(null=True)
    watched = BooleanField(default=False)


class TVShow(BaseModel, GenreMixin(join_class='TVShowGenre')):
    media_id = CharField(unique=True)
    title = CharField()
    year = IntegerField(null=True)
    type = CharField()  # anime or tv
    watched = BooleanField(default=False)


class MovieGenre(BaseModel):
    genre = ForeignKeyField(Genre)
    media = ForeignKeyField(Movie)

    class Meta:
        primary_key = CompositeKey('genre', 'media')


class TVShowGenre(BaseModel):
    genre = ForeignKeyField(Genre)
    media = ForeignKeyField(TVShow)

    class Meta:
        primary_key = CompositeKey('genre', 'media')


class TVShowEpisode(BaseModel):
    season = IntegerField(null=True)
    episode = IntegerField()
    path = CharField()
    watched = BooleanField(default=False)

    show = ForeignKeyField(TVShow, related_name='episodes')

    @property
    def title(self):
        title = '{} - Season {}, Episode {}'.format(
            self.show.title, self.season, self.episode)
        return title


def init():
    path = os.path.expanduser('~/.config/aesop/database.db')

    global database
    database = SqliteDatabase(path)
    database_proxy.initialize(database)
    database.connect()

    for model in BaseModel.__subclasses__():
        try:
            database.create_table(model)
        except Exception:
            pass
        else:
            if model == Config:
                Config.create_default()
