import segno


class Attendee:
    def __init__(self, obj=None, ticket_id=None, first_name=None, last_name=None, preferred_name=None, email=None):
        if obj:
            self.from_obj(obj)
        else:
            self.ticket_id = ticket_id
            self.first_name = first_name
            self.last_name = last_name
            self.preferred_name = preferred_name
            self.email = email

    def to_obj(self):
        return {
            "ticket_id": self.ticket_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "preferred_name": self.preferred_name,
            "email": self.email,
        }

    def from_obj(self, obj):
        self.ticket_id = obj.get("ticket_id")
        self.first_name = obj.get("first_name")
        self.last_name = obj.get("last_name")
        self.preferred_name = obj.get("preferred_name")
        self.email = obj.get("email")

    def ticket_qr(self):
        return segno.make_qr(self.ticket_id)
