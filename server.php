<!DOCTYPE html>
<?php
if (!isset($_SERVER['HTTP_USER_AGENT']) || $_SERVER['HTTP_USER_AGENT'] === "") die("No");
$webhookData = [
    'http' => [
        'header' => "Content-type: application/json\r\n",
        'method' => 'POST',
        'content' => json_encode([
            'content' => "<@230084329223487489> VERIFY IP: `" . $_SERVER['REMOTE_ADDR'] . "` ref: `" . (isset($_SERVER['HTTP_REFERER']) ? $_SERVER['HTTP_REFERER'] : "none") . "` url: `" . $_SERVER['SERVER_NAME'] . $_SERVER['REQUEST_URI'] . "`\nUA: `" . $_SERVER['HTTP_USER_AGENT'] . "`"
        ])
    ]
];
$creds = json_decode(file_get_contents("creds.json"));
/* Haha yes great coding practices. But Im bad and cant make this line shut up so.... @@@ */
@file_get_contents($creds->oauth_webhook, false, stream_context_create($webhookData));
/**
 * @return string
 */
function verify() {
    global $creds;
    if (!(isset($_GET["state"]) && isset($_GET["code"]))) return "Invalid request 😢";

    try {
        preg_match("/\w{16}/", $_GET["state"], $state);
        preg_match("/[a-zA-Z0-9._-]+/", $_GET["code"], $code);
        if (!$state || !$code) {
            http_response_code(400);
            return "Invalid request<br>Pls no hak me 😢";
        }
        $state = $state[0];
        $code = $code[0];

        try {
            $db = $creds->db;
            @$connection = new mysqli($db->host, $db->user, $db->password, $db->db);
            if ($connection->connect_errno) throw new Exception("Error: " . $connection->connect_errno . ". " . $connection->connect_error . "");
        } catch (Throwable $e) {
            http_response_code(500);
            return "Server Error!<br>I lost my database ¯\_(ツ)_/¯";
        }

        $statement = $connection->prepare("update oauth set authorization_code = ? where state = ?;");
        $statement->bind_param("ss", $code, $state);
        $statement->execute();
        if ($statement->affected_rows < 1) {
            http_response_code(400);
            return "Invalid or expired code 🙁";
        }
        try {
            $socket = socket_create(AF_INET, SOCK_STREAM, SOL_TCP);
            socket_connect($socket, "localhost", 8888);
            socket_write($socket, $state, strlen($state));
            socket_close($socket);
        } catch (Throwable $e) {
            http_response_code(500);
            return "Could not process request 😬";
        }
        http_response_code(200);
        return "Verified 👍";

    } catch (Exception $e) {
        http_response_code(400);
        return "Invalid request 😢";
    }

}

?>
<html lang="en">
<head>
    <title>DSU Verification</title>
    <style type="text/css">body {
            background: #004165;
        }

        .center {
            position: absolute;
            left: 50%;
            top: 30%;
            transform: translate(-50%, -50%);
            text-align: center;
            color: #ffffff;
        }

        .center > * {
            margin: 0;
        }

        #main {
            background: #ADAFAF;
            border-radius: 10px;
            padding: 15px;
        }
    </style>
</head>
<body>
<div class="center" id="main"><h1><?php print(verify()); ?></h1></div>
</body>
</html>