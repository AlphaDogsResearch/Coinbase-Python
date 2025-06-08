

def sendSellAlert(bot_message):

    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    pMsg = bot_message.replace("%25", "%")  # For displaying in console
    print(" ".join([pMsg, "at", tijd]))

    send_text = (
        "https://api.telegram.org/bot"
        + bot_token
        + "/sendMessage?chat_id="
        + send_to
        + "&parse_mode=HTML&text="
        + bot_message
    )
    response = requests.get(send_text)