import asyncio
import json
import random
import time

from fasthtml.common import Div, Script, Style, Titled, fast_app, serve
from starlette.websockets import WebSocket, WebSocketDisconnect

app, rt = fast_app()  # NO exts='ws' => We'll define raw websockets ourselves.

# Calculate total size
GRID_SIZE = 20  # cells
CELL_SIZE = 20  # pixels
GAP_SIZE = 2  # pixels
PADDING = 10  # pixels per side
TOTAL_SIZE = (GRID_SIZE * CELL_SIZE) + (GRID_SIZE - 1) * GAP_SIZE + 2 * PADDING
score = 0  # New: Track score
game_over = False  # New: Track game state
snake = [(10, 10)]
direction = "right"
food = None

last_direction_change = 0
connected_clients = set()

opposites = {"left": "right", "right": "left", "up": "down", "down": "up"}


def place_food():
    """Return a random empty position not on the snake."""
    while True:
        fx = random.randint(0, GRID_SIZE - 1)
        fy = random.randint(0, GRID_SIZE - 1)
        if (fx, fy) not in snake:
            return (fx, fy)


def render_grid():
    """Render the board HTML with snake + food."""
    cells = []

    # Add debug markers

    for y in range(GRID_SIZE):
        for x in range(GRID_SIZE):
            cls_ = "grid-cell"
            if (x, y) in snake:
                cls_ += " snake-cell"
            elif (x, y) == food:
                cls_ += " food-cell"
            cells.append(Div(cls=cls_))

    return Div(*cells, id="game-container", cls="grid-container")


# Alternative broadcast_state
async def broadcast_state():
    state = {"snake": snake, "food": food, "direction": direction}
    to_remove = []
    for ws in connected_clients:
        try:
            await ws.send_json(state)
        except BaseException as e:
            print(f"❌ Error sending to {ws}: {e}")
            to_remove.append(ws)
    for ws in to_remove:
        connected_clients.discard(ws)


async def move_snake():
    """Run forever, moving the snake & broadcasting updates."""
    global snake, direction, food
    while True:
        head_x, head_y = snake[0]
        if direction == "left":
            head_x -= 1
        elif direction == "right":
            head_x += 1
        elif direction == "up":
            head_y -= 1
        elif direction == "down":
            head_y += 1

        head_x %= GRID_SIZE
        head_y %= GRID_SIZE

        new_head = (head_x, head_y)
        snake.insert(0, new_head)

        # Food check => grow or pop
        if new_head == food:
            food = place_food()
        else:
            snake.pop()

        await broadcast_state()
        await asyncio.sleep(0.2)


@app.on_event("startup")
async def startup():
    """On server start, place food & begin the snake movement task."""
    global food
    food = place_food()
    asyncio.create_task(move_snake())


@rt("/")
def index():
    """Renders an empty container & the JS for WebSocket."""
    return Titled(
        "Snake WebSockets!",
        # Div("", id="game-container"),  # We'll fill this from the server
        render_grid(),
        Style(
            f"""
            .grid-container {{
                display: grid;
                grid-template-columns: repeat({GRID_SIZE}, {CELL_SIZE}px);
                grid-template-rows: repeat({GRID_SIZE}, {CELL_SIZE}px);
                gap: {GAP_SIZE}px;
                background-color: #333;
                width: {TOTAL_SIZE}px;
                height: {TOTAL_SIZE}px;
                padding: {PADDING}px;
                border-radius: 8px;
                box-shadow: 0 0 10px rgba(0,0,0,0.5);
                border: none;
                box-sizing: border-box;
            }}
            .grid-cell {{
                width: {CELL_SIZE}px;
                height: {CELL_SIZE}px;
                background-color: #666;
                border: none;
                border-radius: 4px;
                transition: background-color 0.1s ease;
            }}
            .snake-cell {{
                background-color: #2ecc71 !important;
                box-shadow: inset 0 0 5px rgba(0,0,0,0.3);
            }}
            .food-cell {{
                background-color: #e74c3c !important;
                border-radius: 50%;
                box-shadow: 0 0 5px #e74c3c;
            }}
            """
        ),
        Script(
            f"""
            let protocol = (window.location.protocol === 'https:') ? 'wss:' : 'ws:';
            let wsUrl = protocol + '//' + window.location.host + '/ws';
            let socket = new WebSocket(wsUrl);

            socket.onopen = () => console.log("✅ WebSocket Connected!");
            socket.onerror = (err) => console.error("❌ WebSocket Error:", err);
            socket.onclose = () => console.warn("⚠️ WebSocket Closed");

            socket.onmessage = (evt) => {{
                const state = JSON.parse(evt.data);
                const cells = document.querySelectorAll('.grid-cell');
                cells.forEach(cell => {{
                    cell.className = 'grid-cell';
                }});
                state.snake.forEach(([x, y]) => {{
                    const index = y * {GRID_SIZE} + x;
                    cells[index].classList.add('snake-cell');
                }});
                const foodIndex = state.food[1] * {GRID_SIZE} + state.food[0];
                cells[foodIndex].classList.add('food-cell');
            }};


            // Arrow keys => JSON with direction
            document.addEventListener('keydown', (e) => {{
                let k = e.key.replace('Arrow','').toLowerCase();
                if (['left','right','up','down'].includes(k)) {{
                    socket.send(JSON.stringify({{ direction: k }}));
                }}
            }});
            """
        ),
    )


#################################################
# Standard Starlette approach to websockets
#################################################
@app.websocket_route("/ws")
# Add this global variable

# In snake_ws websocket handler
async def snake_ws(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    await broadcast_state()

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                d = msg.get("direction", "")
                if not d:
                    continue

                global direction, last_direction_change
                current_time = time.time()
                # Add 100ms debounce
                if current_time - last_direction_change > 0.1 and d in opposites:
                    if opposites[d] != direction:
                        direction = d
                        last_direction_change = current_time
                        print(f"🔄 Direction changed to: {d}")
            except json.JSONDecodeError:
                print("❌ Received invalid JSON:", data)
                continue
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)


serve()
