import os

def cleanup_temp():

    folder="temp"

    if not os.path.exists(folder):
        return

    for file in os.listdir(folder):
        try:
            os.remove(
                os.path.join(folder,file)
            )
        except:
            pass